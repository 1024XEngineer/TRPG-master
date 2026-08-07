"""Issue #121 的 SQLAlchemy Store 与房间运行时生命周期测试。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import cast

import pytest
from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    ContractError,
    Intent,
    JsonObject,
    MatchedTarget,
    ModuleCheck,
    PlayerViewScope,
)
from collaboration_framework.engine import (
    CompletedAction,
    EngineExecutionResult,
    GameState,
    RevisionConflictError,
    RuleEngineService,
    StateModifiedEvent,
)
from collaboration_framework.host.schemas import IntentContext
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import SqlAlchemyEngineStore
from app.core.seed import (
    BUILTIN_MODULE_ID,
    BUILTIN_MODULE_VERSION,
    BUILTIN_SCENARIO_ID,
    BUILTIN_SYSTEM_ID,
)
from app.models.engine import ActionExecution, GameEvent, GameSession
from app.models.room import Character, Player, Room
from app.service import room as room_service
from tests.helpers import create_room, reconnect

_CHARACTER_PAYLOAD = {
    "name": "锁定测试调查员",
    "age": 30,
    "gender": "未知",
    "residence": "上海",
    "birthplace": "杭州",
    "attributes": {
        "STR": 50,
        "CON": 50,
        "POW": 50,
        "DEX": 50,
        "APP": 50,
        "SIZ": 50,
        "INT": 50,
        "EDU": 50,
        "LUCK": 50,
    },
    "derivedStats": {"HP": 10, "MP": 10, "SAN": 50},
    "skills": {},
    "equipment": [],
    "occupation": None,
    "background": "",
    "notes": "",
}


class _CandidateIntentModel:
    async def generate(self, context: IntentContext) -> JsonObject:
        return {
            "kind": "action",
            "verb": "investigate",
            "target": {
                "matched": True,
                "id": context.player_view.scene.id,
            },
            "check": {
                "route": "default",
                "proposed_skills": ["spot-hidden", "stealth"],
            },
            "summary": context.player_input.utterance,
        }


def _uuid(prefix: int, value: int) -> str:
    return f"{prefix:08d}-0000-0000-0000-{value:012d}"


async def _create_building_room(
    db: AsyncSession,
    *,
    room_number: int = 1,
    player_count: int = 1,
) -> tuple[Room, list[Player], list[Character]]:
    room = Room(
        id=_uuid(50000000, room_number),
        room_code=f"R{room_number:05d}",
        room_name=f"运行时测试房间 {room_number}",
        max_players=player_count,
        phase="Building",
        scenario_id=BUILTIN_SCENARIO_ID,
        module_version=BUILTIN_MODULE_VERSION,
        system_id=BUILTIN_SYSTEM_ID,
    )
    players: list[Player] = []
    characters: list[Character] = []
    joined_at = datetime(2026, 7, 23, tzinfo=UTC)
    for player_number in range(1, player_count + 1):
        identity = room_number * 10 + player_number
        player = Player(
            id=_uuid(51000000, identity),
            room_id=room.id,
            nickname=f"玩家 {player_number}",
            is_host=player_number == 1,
            has_character=True,
            reconnect_token=_uuid(53000000, identity),
            joined_at=joined_at + timedelta(seconds=player_number),
        )
        character = Character(
            id=_uuid(52000000, identity),
            room_id=room.id,
            player_id=player.id,
            status="complete",
            version=player_number + 2,
            name=f"调查员 {player_number}",
            age=20 + player_number,
            gender="未知",
            residence="上海",
            birthplace="杭州",
            generation_method="pointbuy",
            occupation="私家侦探",
            attributes={"HP_SOURCE": player_number},
            derived_stats={"HP": 10 + player_number},
            skills={"spot-hidden": 50 + player_number},
            equipment=["手电筒"],
            background=f"背景 {player_number}",
            notes="",
        )
        players.append(player)
        characters.append(character)
    room.host_player_id = players[0].id
    db.add_all([room, *players, *characters])
    await db.commit()
    return room, players, characters


async def _start_room(
    db: AsyncSession,
    *,
    room_number: int = 1,
    player_count: int = 1,
    prepare_checkpoint: bool = True,
) -> tuple[Room, list[Player], list[Character]]:
    room, players, characters = await _create_building_room(
        db,
        room_number=room_number,
        player_count=player_count,
    )
    await room_service.begin_game(db, room.id, players[0].id)
    if prepare_checkpoint:
        game_session = await db.get(GameSession, room.id)
        assert game_session is not None
        state = GameState.model_validate(game_session.state_json)
        cemetery_figure = dict(state.entities["cemetery_figure"])
        cemetery_figure.update(willing_to_talk=True, truth_told=True)
        game_session.state_json = state.model_copy(
            update={
                "scene_id": "conversation",
                "entities": {
                    **state.entities,
                    "cemetery_figure": cemetery_figure,
                },
            },
            deep=True,
        ).to_json_dict()
        await db.commit()
    return room, players, characters


def _checkpoint_request(
    *,
    room_id: str,
    player_id: str,
    request_id: str = "request-121",
    revision: str = "0",
) -> ActionRequest:
    return ActionRequest(
        request_id=request_id,
        room_id=room_id,
        player_id=player_id,
        actor_id="actor_1",
        source_view_revision=revision,
        intent=Intent(
            kind="action",
            verb="follow",
            target=MatchedTarget(id="cemetery_figure"),
            check=ModuleCheck(
                checkpoint_id="follow_douglas_underground",
                proposed_skills=(),
            ),
            summary="跟随道格拉斯进入地下",
        ),
    )


def _commit_payload(
    request: ActionRequest,
    runtime,
) -> tuple[GameState, tuple[StateModifiedEvent, ...], CompletedAction]:
    """One well-formed write, assembled by hand.

    These store tests used to get their payload from `RuleKernel.execute`. The
    kernel is gone (#226) but the SQLAlchemy store's atomicity is not v2 — the
    adjudication path commits through the same tables — so the payload is built
    here and the assertions below are unchanged.
    """

    new_state = runtime.game_state.model_copy(deep=True)
    new_state.entities["case_tracker"]["investigator_disappeared"] = True
    new_state = new_state.model_copy(
        update={"event_sequence": runtime.game_state.event_sequence + 1}
    )
    events = (
        StateModifiedEvent(
            event_id=f"evt-{request.request_id}",
            sequence=new_state.event_sequence,
            room_id=request.room_id,
            actor_id=request.actor_id,
            client_action_id=request.request_id,
            cause=f"action:{request.request_id}",
            payload={
                "path": "entities.case_tracker.investigator_disappeared",
                "from": False,
                "to": True,
            },
        ),
    )
    completed = CompletedAction(
        request=request,
        execution=EngineExecutionResult(
            action_result=ActionResult(
                request_id=request.request_id,
                action_id=request.request_id,
                resolution="checkpoint",
                outcome="success",
                view_revision=str(new_state.event_sequence),
                event_refs=tuple(event.event_id for event in events),
            ),
            events=events,
            state_version=new_state.event_sequence,
        ),
    )
    return new_state, events, completed


async def _commit_once(
    store: SqlAlchemyEngineStore,
    request: ActionRequest,
) -> CompletedAction:
    async with store.transaction(request.room_id) as transaction:
        runtime = await transaction.load_runtime()
        new_state, events, completed = _commit_payload(request, runtime)
        await transaction.commit(
            expected_revision=runtime.revision,
            new_state=new_state,
            events=events,
            completed_action=completed,
        )
    return completed


async def _counts(db: AsyncSession, room_id: str) -> tuple[int, int]:
    events = await db.scalar(
        select(func.count()).select_from(GameEvent).where(GameEvent.room_id == room_id)
    )
    actions = await db.scalar(
        select(func.count()).select_from(ActionExecution).where(ActionExecution.room_id == room_id)
    )
    return int(events or 0), int(actions or 0)


def test_application_composes_sqlalchemy_engine_store() -> None:
    from app.core.engine import engine_store, rule_engine_service

    assert isinstance(engine_store, SqlAlchemyEngineStore)
    assert rule_engine_service._store is engine_store


async def test_select_module_pins_recommended_published_version(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    room = await create_room(client, max_players=1)
    response = await client.post(
        f"/api/v1/rooms/{room['roomId']}/module",
        json={
            "moduleId": BUILTIN_MODULE_ID,
            "attributeGenMethod": "point_buy",
        },
        headers=reconnect(room["reconnectToken"]),
    )

    assert response.status_code == 200
    stored_room = await db_session.get(Room, room["roomId"])
    assert stored_room is not None
    assert stored_room.scenario_id == BUILTIN_SCENARIO_ID
    assert stored_room.module_version == BUILTIN_MODULE_VERSION


async def test_begin_game_creates_stable_actor_snapshots(
    db_session: AsyncSession,
) -> None:
    room, players, characters = await _start_room(
        db_session,
        player_count=2,
        prepare_checkpoint=False,
    )

    game_session = await db_session.get(GameSession, room.id)
    assert game_session is not None
    state = GameState.model_validate(game_session.state_json)
    await db_session.refresh(room)

    assert room.phase == "InGame"
    assert room.started_at is not None
    assert game_session.module_id == BUILTIN_MODULE_ID
    assert game_session.module_version == BUILTIN_MODULE_VERSION
    assert game_session.state_version == state.event_sequence == 0
    assert state.scene_id == "client_briefing"
    assert state.phase == "playing"
    assert list(state.actors) == ["actor_1", "actor_2"]
    assert state.actors["actor_1"].player_id == players[0].id
    assert state.actors["actor_2"].player_id == players[1].id
    assert state.actors["actor_1"].source_character_id == characters[0].id
    assert state.actors["actor_1"].source_character_version == characters[0].version
    assert "actor_1" not in {character.id for character in characters}
    assert state.actors["actor_1"].state["attributes"] == {"HP_SOURCE": 1}
    actor_skills = state.actors["actor_1"].state["skills"]
    assert isinstance(actor_skills, dict)
    assert actor_skills["library-use"] == 20
    assert actor_skills["credit-rating"] == 0
    assert actor_skills["spot-hidden"] == 51
    assert state.actors["actor_1"].resources.hp == 11
    assert state.actors["actor_1"].resources.san is None
    assert state.entities["thomas"]["case_open"] is True
    assert state.entities["case_tracker"]["investigator_disappeared"] is False

    assert await room_service.begin_game(db_session, room.id, players[0].id) is False
    assert (
        await db_session.scalar(
            select(func.count()).select_from(GameSession).where(GameSession.room_id == room.id)
        )
        == 1
    )


async def test_load_runtime_backfills_ruleset_skills_for_legacy_actor(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(
        db_session,
        prepare_checkpoint=False,
    )
    room_id = room.id
    game_session = await db_session.get(GameSession, room_id)
    assert game_session is not None
    state = GameState.model_validate(game_session.state_json)
    actor = state.actors["actor_1"]
    legacy_actor_state = dict(actor.state)
    legacy_actor_state["skills"] = {
        "library-use": 44,
        "spot-hidden": 51,
        "persuade": 35,
        "credit-rating": 10,
    }
    legacy_actor_state.pop("skill_labels", None)
    legacy_state = state.model_copy(
        update={
            "actors": {
                **state.actors,
                "actor_1": actor.model_copy(update={"state": legacy_actor_state}),
            }
        }
    )
    game_session.state_json = legacy_state.to_json_dict()
    await db_session.commit()

    store = engine_store_factory()
    async with store.transaction(room_id) as transaction:
        runtime = await transaction.load_runtime()

    actor_state = runtime.game_state.actors["actor_1"].state
    skills = cast(dict[str, int], actor_state["skills"])
    skill_labels = cast(dict[str, str], actor_state["skill_labels"])
    assert len(skills) > 4
    assert skills["stealth"] == 20
    assert skills["library-use"] == 44
    assert skill_labels["stealth"] == "潜行"
    assert runtime.revision == "0"

    projection = await RuleEngineService(store).read(
        PlayerViewScope(
            room_id=room_id,
            player_id=players[0].id,
            actor_id="actor_1",
        )
    )
    stealth = next(skill for skill in projection.self_actor.skills if skill.id == "stealth")
    assert stealth.value == 20
    assert stealth.name == "潜行"

    db_session.expire_all()
    persisted = await db_session.get(GameSession, room_id)
    assert persisted is not None
    persisted_state = GameState.model_validate(persisted.state_json)
    persisted_skills = cast(
        dict[str, int],
        persisted_state.actors["actor_1"].state["skills"],
    )
    assert persisted.state_version == 0
    assert persisted_skills["stealth"] == 20


async def test_character_reads_remain_available_and_writes_conflict_after_game_start(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    room, players, characters = await _start_room(db_session)
    original_version = characters[0].version
    headers = {"X-Reconnect-Token": players[0].reconnect_token}

    read_response = await client.get(
        f"/api/v1/rooms/{room.id}/characters/{characters[0].id}",
        headers=headers,
    )
    assert read_response.status_code == 200

    patch_response = await client.patch(
        f"/api/v1/rooms/{room.id}/characters/{characters[0].id}",
        json=_CHARACTER_PAYLOAD,
        headers=headers,
    )
    complete_response = await client.post(
        f"/api/v1/rooms/{room.id}/characters/{characters[0].id}/complete",
        headers=headers,
    )
    roll_response = await client.post(
        f"/api/v1/rooms/{room.id}/characters/{characters[0].id}/roll-attributes",
        headers=headers,
    )

    for response in (patch_response, complete_response, roll_response):
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "CONFLICT"
    await db_session.refresh(characters[0])
    assert characters[0].version == original_version


async def test_suspended_room_rejects_commits_and_resume_restores_them(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    """暂停中不许写，恢复后恢复可写——这道闸门在 store 的 commit 里（不在被删的
    execute 里），裁决路径命中的是同一段 `Room.phase == "InGame"` 守卫。"""

    room, players, _ = await _start_room(db_session)
    store = engine_store_factory()

    await room_service.suspend_game(db_session, room.id, players[0].reconnect_token)
    await db_session.refresh(room)
    game_session = await db_session.get(GameSession, room.id)
    assert game_session is not None
    assert room.phase == "Suspended"
    assert GameState.model_validate(game_session.state_json).phase == "playing"

    # 读始终允许：暂停挡的是写，不是看。
    projection = await RuleEngineService(store).read(
        PlayerViewScope(
            room_id=room.id,
            player_id=players[0].id,
            actor_id="actor_1",
        )
    )
    assert projection.revision == "0"

    request = _checkpoint_request(room_id=room.id, player_id=players[0].id)
    with pytest.raises(ContractError, match="InGame"):
        await _commit_once(store, request)
    assert await _counts(db_session, room.id) == (0, 0)

    await room_service.resume_game(db_session, room.id, players[0].reconnect_token)
    completed = await _commit_once(store, request)

    room_id = room.id
    db_session.expire_all()
    assert await _counts(db_session, room_id) == (
        len(completed.execution.action_result.event_refs),
        1,
    )


async def test_manual_end_from_suspended_syncs_room_and_game_state(
    db_session: AsyncSession,
    sql_counter: list[str],
) -> None:
    room, players, _ = await _start_room(db_session)
    await room_service.suspend_game(db_session, room.id, players[0].reconnect_token)
    sql_counter.clear()
    await room_service.end_game(db_session, room.id, players[0].reconnect_token)

    await db_session.refresh(room)
    game_session = await db_session.get(GameSession, room.id)
    assert game_session is not None
    state = GameState.model_validate(game_session.state_json)
    assert room.phase == "Completed"
    assert state.phase == "ended"
    assert state.ending_id is None
    assert state.event_sequence == game_session.state_version == 0
    updates = [
        statement.lower().lstrip()
        for statement in sql_counter
        if statement.lower().lstrip().startswith("update ")
    ]
    room_update_index = next(
        index for index, statement in enumerate(updates) if statement.startswith("update rooms ")
    )
    state_update_index = next(
        index
        for index, statement in enumerate(updates)
        if statement.startswith("update game_sessions ")
    )
    assert room_update_index < state_update_index

    with pytest.raises(room_service.RoomConflictError):
        await room_service.resume_game(db_session, room.id, players[0].reconnect_token)


async def test_store_persists_completed_action_across_store_rebuild(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(db_session)
    request = _checkpoint_request(room_id=room.id, player_id=players[0].id)
    completed = await _commit_once(engine_store_factory(), request)

    # 换一个 store 实例：幂等记录必须来自数据库，而不是进程内缓存。
    async with engine_store_factory().transaction(room.id) as transaction:
        replayed = await transaction.find_completed_action(request.request_id)
    assert replayed == completed

    room_id = room.id
    db_session.expire_all()
    game_session = await db_session.get(GameSession, room_id)
    action = await db_session.get(ActionExecution, (room_id, request.request_id))
    assert game_session is not None
    assert action is not None
    state = GameState.model_validate(game_session.state_json)
    assert action.committed_state_version == state.event_sequence
    assert await _counts(db_session, room_id) == (
        len(completed.execution.action_result.event_refs),
        1,
    )


async def test_loaded_runtime_is_deep_copy_isolated(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, _, _ = await _start_room(db_session)
    store = engine_store_factory()

    async with store.transaction(room.id) as transaction:
        runtime = await transaction.load_runtime()
        runtime.game_state.entities["case_tracker"]["investigator_disappeared"] = True
        runtime.v2.entities[0].direct_responses["invented"] = "泄漏"

    async with store.transaction(room.id) as transaction:
        reloaded = await transaction.load_runtime()

    assert reloaded.game_state.entities["case_tracker"]["investigator_disappeared"] is False
    assert "invented" not in reloaded.v2.entities[0].direct_responses


async def test_store_rejects_stale_revision_without_partial_writes(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(db_session)
    store = engine_store_factory()
    request = _checkpoint_request(room_id=room.id, player_id=players[0].id)

    async with store.transaction(room.id) as transaction:
        runtime = await transaction.load_runtime()
        new_state, events, completed = _commit_payload(request, runtime)
        with pytest.raises(RevisionConflictError):
            await transaction.commit(
                expected_revision="999",
                new_state=new_state,
                events=events,
                completed_action=completed,
            )

    room_id = room.id
    db_session.expire_all()
    game_session = await db_session.get(GameSession, room_id)
    assert game_session is not None
    assert game_session.state_version == 0
    assert await _counts(db_session, room_id) == (0, 0)


async def test_store_failure_rolls_back_state_events_action_and_room(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(db_session)

    def fail_before_commit(room_id: str) -> None:
        raise RuntimeError(f"simulated failure for {room_id}")

    request = _checkpoint_request(room_id=room.id, player_id=players[0].id)
    with pytest.raises(RuntimeError, match="simulated failure"):
        await _commit_once(engine_store_factory(before_commit=fail_before_commit), request)

    room_id = room.id
    db_session.expire_all()
    unchanged_room = await db_session.get(Room, room_id)
    game_session = await db_session.get(GameSession, room_id)
    assert unchanged_room is not None
    assert game_session is not None
    assert unchanged_room.phase == "InGame"
    assert game_session.state_version == 0
    assert GameState.model_validate(game_session.state_json).phase == "playing"
    assert await _counts(db_session, room_id) == (0, 0)


async def test_same_request_id_is_isolated_between_rooms(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    first_room, first_players, _ = await _start_room(db_session, room_number=1)
    second_room, second_players, _ = await _start_room(db_session, room_number=2)
    store = engine_store_factory()

    first = await _commit_once(
        store,
        _checkpoint_request(
            room_id=first_room.id,
            player_id=first_players[0].id,
            request_id="shared-request",
        ),
    )
    second = await _commit_once(
        store,
        _checkpoint_request(
            room_id=second_room.id,
            player_id=second_players[0].id,
            request_id="shared-request",
        ),
    )

    assert first.request.request_id == second.request.request_id == "shared-request"
    assert await _counts(db_session, first_room.id) == (
        len(first.execution.action_result.event_refs),
        1,
    )
    assert await _counts(db_session, second_room.id) == (
        len(second.execution.action_result.event_refs),
        1,
    )
