from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.keeper import _player_safe_action
from app.models.room import Character
from app.module_runtime import ModuleLoader
from app.runtime.contracts import (
    ActionRequest,
    ActionResult,
    Intent,
    PendingCheck,
    RuntimeEvent,
)
from app.runtime.dice import FixedDiceRoller, SystemDiceRoller
from app.runtime.engine import ActionExecutor, StaleRevisionError
from app.runtime.projector import PlayerViewProjector
from app.runtime.state import GameState
from app.runtime.store import SQLAlchemyGameStateStore
from app.service import room as room_service
from tests.helpers import ROOMS_BASE, create_room, reconnect


def _runtime_state() -> tuple[Any, GameState]:
    runtime = ModuleLoader().load_default(allow_uncleared=True)
    source = runtime.package.content.characters[0]
    stat_block = source["stat_block"]
    character = Character(
        id="character-snapshot",
        room_id="room",
        player_id="player",
        status="complete",
        name=source["name"],
        occupation=source["occupation"],
        attributes=stat_block["attributes"],
        derived_stats=stat_block["derived_stats"],
        skills=stat_block["skills"],
        equipment=stat_block["equipment"],
        background=stat_block["background"],
    )
    state = GameState.create(
        room_id="room",
        room_session_id="session",
        scenario_revision_id="revision",
        runtime_module=runtime,
        character=character,
    )
    return runtime, state


def _first_by_type(root: Any, allowed: set[str]) -> dict[str, dict[str, Any]]:
    found: dict[str, dict[str, Any]] = {}

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            item_type = value.get("type")
            if item_type in allowed and item_type not in found:
                found[item_type] = value
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(root)
    return found


def test_coc7_dice_grades_and_expression_parser() -> None:
    executor = ActionExecutor(dice=FixedDiceRoller([1]))

    assert executor._check_grade(1, 40) == "critical"
    assert executor._check_grade(8, 40) == "extreme"
    assert executor._check_grade(20, 40) == "hard"
    assert executor._check_grade(40, 40) == "regular"
    assert executor._check_grade(41, 40) == "failure"
    assert executor._check_grade(96, 40) == "fumble"
    assert executor._check_grade(100, 80) == "fumble"
    assert 3 <= SystemDiceRoller().expression("2d6+1") <= 13
    with pytest.raises(ValueError, match="不支持"):
        SystemDiceRoller().expression("import os")


def test_skill_and_san_checks_only_use_server_dice() -> None:
    runtime, state = _runtime_state()
    state.current_scene_id = "scene.neighborhood"
    actor = state.actors["character-snapshot"]
    executor = ActionExecutor(dice=FixedDiceRoller([20, 80, 4]))
    events = []
    narration_facts: list[str] = []
    pending = executor._request_checkpoint(
        state,
        runtime,
        actor,
        Intent(
            kind="checkpoint",
            summary="询问邻居",
            checkpoint_id="check.social_neighbors",
            skill_id="fast_talk",
        ),
        events,
    )

    grade = executor._resolve_skill_check(
        state, runtime, actor, pending, events, narration_facts
    )

    assert grade in {"critical", "extreme", "hard", "regular"}
    assert events[-1].payload["rollValue"] == 20
    assert "clue.douglas_read_at_cemetery" in state.granted_clue_ids

    san_pending = PendingCheck(
        check_request_id="san-request",
        kind="san",
        actor_id=actor.actor_id,
        sanity_event_id="san.see_douglas",
        target_value=actor.current_san,
        reason="看见道格拉斯",
    )
    san_outcome = executor._resolve_san_check(
        state, runtime, actor, san_pending, events
    )

    assert san_outcome == "san_failure"
    assert events[-1].payload["rollValue"] == 80
    assert events[-1].payload["sanLoss"] == 4


def test_keeper_model_only_receives_player_safe_action_result() -> None:
    action = ActionResult(
        request_id="request",
        resolution="resolved",
        outcome="action_resolved",
        state_revision=1,
        state_changed=True,
        narration_facts=["fact.hidden_truth"],
        events=[
            RuntimeEvent(
                event_type="trigger.fired",
                payload={"secret": "keeper truth"},
                visibility="keeper",
            ),
            RuntimeEvent(
                event_type="clue.granted",
                payload={"description": "玩家已经获得的线索"},
                visibility="player",
            ),
        ],
    )

    safe = _player_safe_action(action)

    assert safe.narration_facts == []
    assert [event.event_type for event in safe.events] == ["clue.granted"]
    assert "keeper truth" not in safe.model_dump_json()


def test_scene_entry_trigger_and_dialogue_reach_peaceful_ending() -> None:
    runtime, state = _runtime_state()
    state.current_scene_id = "scene.cemetery"
    executor = ActionExecutor(dice=FixedDiceRoller([20, 1, 3]))
    events: list[RuntimeEvent] = []
    narration_facts: list[str] = []

    pending = executor._execute_intent(
        state,
        runtime,
        Intent(
            kind="choice",
            summary="进入地穴",
            choice_id="scene.crypt",
        ),
        "我进入地穴",
        events,
        narration_facts,
    )

    assert state.current_scene_id == "scene.douglas_conversation"
    assert pending is not None
    assert pending.kind == "san"
    assert pending.sanity_event_id == "san.see_douglas"
    assert "trigger.douglas_waits_at_crypt" in state.fired_trigger_ids

    state.pending_checks.clear()
    events.clear()
    executor._execute_intent(
        state,
        runtime,
        Intent(kind="dialogue", summary="礼貌听道格拉斯解释"),
        "我礼貌地听他说完",
        events,
        narration_facts,
    )

    assert "clue.douglas_truth" in state.granted_clue_ids
    assert state.pending_checks[0].sanity_event_id == "san.learn_douglas_truth"
    assert state.active_ending_id == "ending.peaceful_resolution"
    assert any(event.event_type == "game.ended" for event in events)


def test_all_package_condition_and_effect_types_are_executable() -> None:
    runtime, state = _runtime_state()
    executor = ActionExecutor(dice=FixedDiceRoller([2, 3, 4]))
    required_conditions = set(
        runtime.package.module.ruleset_ref.required_condition_types
    )
    required_effects = set(runtime.package.module.ruleset_ref.required_effect_types)
    conditions = _first_by_type(runtime.package_json["content"], required_conditions)
    effects = _first_by_type(runtime.package_json["content"], required_effects)

    assert set(conditions) == required_conditions
    assert set(effects) == required_effects

    executor._set_path(state, "object.liquor_bottle.noticed", True)
    state.last_check = {
        "grade": "fumble",
        "checkpoint_id": "check.find_speakeasy",
    }
    state.variables["player.choice"] = "follow_douglas_underground"
    state.variables["temporary_insanity_during_ghoul_crowd"] = True
    attack_context = {
        "intent": {"kind": "choice", "choice_id": "attack_ghouls"}
    }
    for condition_type, condition in conditions.items():
        context = attack_context if condition_type == "player_attacks" else {}
        assert executor._conditions_met([condition], state, runtime, context)

    for effect_type, effect in effects.items():
        _, isolated = _runtime_state()
        executor._set_path(isolated, "object.study_window.locked", True)
        events = []
        narration_facts: list[str] = []
        executor._apply_effects(
            isolated,
            runtime,
            [effect],
            {"utterance": ""},
            events,
            narration_facts,
        )
        if effect_type == "conditional_hazard":
            assert isolated.variables["hazard.unconscious_until_night"] is True


@pytest.mark.parametrize(
    ("ending_id", "prepare", "context"),
    [
        (
            "ending.peaceful_resolution",
            lambda executor, state: executor._set_path(
                state, "npc.douglas.conversation_completed", True
            ),
            {},
        ),
        (
            "ending.follow_underground",
            lambda _executor, state: state.variables.__setitem__(
                "player.choice", "follow_douglas_underground"
            ),
            {},
        ),
        (
            "ending.overpowered_by_ghouls",
            lambda _executor, _state: None,
            {"intent": {"kind": "choice", "choice_id": "attack_ghouls"}},
        ),
        (
            "ending.asylum",
            lambda _executor, state: state.variables.__setitem__(
                "temporary_insanity_during_ghoul_crowd", True
            ),
            {},
        ),
        (
            "ending.flee_after_douglas_death",
            lambda executor, state: (
                executor._set_path(state, "npc.douglas.alive", False),
                state.variables.__setitem__("player.choice", "flee"),
            ),
            {},
        ),
        (
            "ending.arrested",
            lambda _executor, state: setattr(
                state,
                "last_check",
                {
                    "grade": "fumble",
                    "checkpoint_id": "check.find_speakeasy",
                },
            ),
            {},
        ),
    ],
)
def test_all_six_endings_are_resolved(
    ending_id: str,
    prepare,
    context: dict[str, Any],
) -> None:
    runtime, state = _runtime_state()
    executor = ActionExecutor(dice=FixedDiceRoller([1]))
    prepare(executor, state)
    events = []

    executor._evaluate_endings(state, runtime, events, context=context)

    assert state.active_ending_id == ending_id
    assert events[-1].event_type == "game.ended"


async def _started_runtime(
    client: AsyncClient,
    db: AsyncSession,
) -> tuple[dict, Any, Character]:
    room = await create_room(client, max_players=1)
    module = (await client.get("/api/v1/modules")).json()["data"][0]
    detail = (await client.get(f"/api/v1/modules/{module['id']}")).json()["data"]
    await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": module["id"]},
        headers=reconnect(room["reconnectToken"]),
    )
    await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/start-story",
        headers=reconnect(room["reconnectToken"]),
    )
    created = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters",
        json={"basedOnPregenId": detail["pregens"][0]["id"]},
        headers=reconnect(room["reconnectToken"]),
    )
    character_id = created.json()["data"]["characterId"]
    view = await room_service.begin_game(db, room["roomId"], room["playerId"])
    character = await db.scalar(select(Character).where(Character.id == character_id))
    assert character is not None
    return room, view, character


async def test_action_executor_is_idempotent_and_detects_stale_state(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    room, view, character = await _started_runtime(client, db_session)
    executor = ActionExecutor(dice=FixedDiceRoller([20]))
    request = ActionRequest(
        request_id="same-request",
        room_id=room["roomId"],
        room_session_id=view.room_session_id,
        player_id=room["playerId"],
        actor_id=character.id,
        source_revision=view.state_revision,
        utterance="环顾四周",
        intent=Intent(kind="free", summary="环顾四周"),
    )

    first = await executor.execute(db_session, request)
    replayed = await executor.execute(db_session, request)

    assert first.state_revision == 1
    assert replayed.resolution == "replayed"
    assert replayed.state_revision == first.state_revision

    stale = request.model_copy(
        update={"request_id": "stale-request", "source_revision": 0}
    )
    with pytest.raises(StaleRevisionError):
        await executor.execute(db_session, stale)

    state = await SQLAlchemyGameStateStore().load(
        db_session, view.room_session_id
    )
    session = await SQLAlchemyGameStateStore().active_session(
        db_session, room["roomId"]
    )
    assert session is not None
    runtime = await SQLAlchemyGameStateStore().module_for_session(
        db_session, session
    )
    projected = PlayerViewProjector().project(
        state, runtime, actor_id=character.id
    )
    assert projected.state_revision == 1
