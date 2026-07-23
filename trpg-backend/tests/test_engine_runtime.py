"""Issue #121 的 SQLAlchemy Store 与房间运行时生命周期测试。"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from collaboration_framework.contracts import (
    ActionRequest,
    ContractError,
    Intent,
    MatchedTarget,
    ModuleCheck,
    PlayerInput,
)
from collaboration_framework.engine import (
    CompletedAction,
    GameState,
    RevisionConflictError,
    RuleEngineService,
    RuleKernel,
)
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters import SqlAlchemyEngineStore
from app.core.seed import (
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
) -> tuple[Room, list[Player], list[Character]]:
    room, players, characters = await _create_building_room(
        db,
        room_number=room_number,
        player_count=player_count,
    )
    await room_service.begin_game(db, room.id, players[0].id)
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
            verb="search",
            target=MatchedTarget(id="location-old-bookshop"),
            check=ModuleCheck(
                checkpoint_id="checkpoint-search-ledger",
                proposed_skills=("spot-hidden",),
            ),
            summary="搜索旧书店账本",
        ),
    )


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
    room = await create_room(client)
    response = await client.post(
        f"/api/v1/rooms/{room['roomId']}/module",
        json={
            "moduleId": BUILTIN_SCENARIO_ID,
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
    room, players, characters = await _start_room(db_session, player_count=2)

    game_session = await db_session.get(GameSession, room.id)
    assert game_session is not None
    state = GameState.model_validate(game_session.state_json)
    await db_session.refresh(room)

    assert room.phase == "InGame"
    assert room.started_at is not None
    assert game_session.module_id == BUILTIN_SCENARIO_ID
    assert game_session.module_version == BUILTIN_MODULE_VERSION
    assert game_session.state_version == state.event_sequence == 0
    assert state.scene_id == "scene-old-bookshop"
    assert state.phase == "playing"
    assert list(state.actors) == ["actor_1", "actor_2"]
    assert state.actors["actor_1"].player_id == players[0].id
    assert state.actors["actor_2"].player_id == players[1].id
    assert state.actors["actor_1"].source_character_id == characters[0].id
    assert state.actors["actor_1"].source_character_version == characters[0].version
    assert "actor_1" not in {character.id for character in characters}
    assert state.actors["actor_1"].state["attributes"] == {"HP_SOURCE": 1}
    assert state.entities["location-old-bookshop"]["ledger_found"] is False

    with pytest.raises(room_service.RoomConflictError):
        await room_service.begin_game(db_session, room.id, players[0].id)
    assert (
        await db_session.scalar(
            select(func.count()).select_from(GameSession).where(GameSession.room_id == room.id)
        )
        == 1
    )


async def test_character_changes_return_conflict_after_game_start(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    room, players, characters = await _start_room(db_session)
    original_version = characters[0].version

    response = await client.patch(
        f"/api/v1/rooms/{room.id}/characters/{characters[0].id}",
        json=_CHARACTER_PAYLOAD,
        headers={"X-Reconnect-Token": players[0].reconnect_token},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONFLICT"
    await db_session.refresh(characters[0])
    assert characters[0].version == original_version


async def test_suspend_blocks_new_actions_and_resume_allows_rule_ending(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(db_session)
    store = engine_store_factory()
    service = RuleEngineService(store)

    await room_service.suspend_game(db_session, room.id, players[0].reconnect_token)
    await db_session.refresh(room)
    game_session = await db_session.get(GameSession, room.id)
    assert game_session is not None
    assert room.phase == "Suspended"
    assert GameState.model_validate(game_session.state_json).phase == "playing"

    projection = await service.read(
        PlayerInput(
            room_id=room.id,
            player_id=players[0].id,
            actor_id="actor_1",
            client_action_id="read-suspended",
            utterance="查看房间",
        )
    )
    assert projection.revision == "0"
    with pytest.raises(ContractError, match="InGame"):
        await service.execute(_checkpoint_request(room_id=room.id, player_id=players[0].id))
    assert await _counts(db_session, room.id) == (0, 0)

    await room_service.resume_game(db_session, room.id, players[0].reconnect_token)
    result = await service.execute(_checkpoint_request(room_id=room.id, player_id=players[0].id))
    assert result.event_refs

    room_id = room.id
    db_session.expire_all()
    completed_room = await db_session.get(Room, room_id)
    completed_session = await db_session.get(GameSession, room_id)
    assert completed_room is not None
    assert completed_session is not None
    completed_state = GameState.model_validate(completed_session.state_json)
    assert completed_state.phase == "ended"
    assert completed_state.ending_id == "ending-ledger-found"
    assert completed_room.phase == "Completed"
    assert completed_room.ended_at is not None


async def test_manual_end_from_suspended_syncs_room_and_game_state(
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(db_session)
    await room_service.suspend_game(db_session, room.id, players[0].reconnect_token)
    await room_service.end_game(db_session, room.id, players[0].reconnect_token)

    await db_session.refresh(room)
    game_session = await db_session.get(GameSession, room.id)
    assert game_session is not None
    state = GameState.model_validate(game_session.state_json)
    assert room.phase == "Completed"
    assert state.phase == "ended"
    assert state.ending_id is None
    assert state.event_sequence == game_session.state_version == 0

    with pytest.raises(room_service.RoomConflictError):
        await room_service.resume_game(db_session, room.id, players[0].reconnect_token)


async def test_store_persists_and_replays_completed_action_after_rebuild(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(db_session)
    request = _checkpoint_request(room_id=room.id, player_id=players[0].id)
    first = await RuleEngineService(engine_store_factory()).execute(request)
    replay = await RuleEngineService(engine_store_factory()).execute(request)

    assert replay == first
    room_id = room.id
    db_session.expire_all()
    game_session = await db_session.get(GameSession, room_id)
    action = await db_session.get(ActionExecution, (room_id, request.request_id))
    assert game_session is not None
    assert action is not None
    state = GameState.model_validate(game_session.state_json)
    assert action.committed_state_version == state.event_sequence
    assert await _counts(db_session, room_id) == (len(first.event_refs), 1)


async def test_loaded_runtime_is_deep_copy_isolated(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, _, _ = await _start_room(db_session)
    store = engine_store_factory()

    async with store.transaction(room.id) as transaction:
        runtime = await transaction.load_runtime()
        runtime.game_state.entities["location-old-bookshop"]["ledger_found"] = True
        runtime.module_content.entities[0].direct_responses["invented"] = "泄漏"

    async with store.transaction(room.id) as transaction:
        reloaded = await transaction.load_runtime()

    assert reloaded.game_state.entities["location-old-bookshop"]["ledger_found"] is False
    assert "invented" not in reloaded.module_content.entities[0].direct_responses


async def test_store_rejects_stale_revision_without_partial_writes(
    db_session: AsyncSession,
    engine_store_factory: Callable[..., SqlAlchemyEngineStore],
) -> None:
    room, players, _ = await _start_room(db_session)
    store = engine_store_factory()
    request = _checkpoint_request(room_id=room.id, player_id=players[0].id)

    async with store.transaction(room.id) as transaction:
        runtime = await transaction.load_runtime()
        execution, new_state = RuleKernel().execute(
            request=request,
            module_content=runtime.module_content,
            game_state=runtime.game_state,
        )
        with pytest.raises(RevisionConflictError):
            await transaction.commit(
                expected_revision="999",
                new_state=new_state,
                events=execution.events,
                completed_action=CompletedAction(
                    request=request,
                    execution=execution,
                ),
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
        await RuleEngineService(engine_store_factory(before_commit=fail_before_commit)).execute(
            request
        )

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

    first = await RuleEngineService(store).execute(
        _checkpoint_request(
            room_id=first_room.id,
            player_id=first_players[0].id,
            request_id="shared-request",
        )
    )
    second = await RuleEngineService(store).execute(
        _checkpoint_request(
            room_id=second_room.id,
            player_id=second_players[0].id,
            request_id="shared-request",
        )
    )

    assert first.request_id == second.request_id == "shared-request"
    assert await _counts(db_session, first_room.id) == (len(first.event_refs), 1)
    assert await _counts(db_session, second_room.id) == (len(second.event_refs), 1)
