"""记忆契约、增量投影、并发幂等和摘要竞态的回归测试。"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import cast

import pytest
from collaboration_framework.contracts import PlayerView
from collaboration_framework.host.schemas import (
    ActionPlanNarrationContext,
    ConversationSummary,
    MemoryContext,
    MemoryEntry,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.sqlalchemy_memory import _listener_memories
from app.controller.ws import _listener_ids_for_utterance
from app.models.engine import GameEvent, GameSession, ModuleVersion
from app.models.event import Event
from app.models.memory import (
    ConversationSummaryRecord,
    MemoryEntryRecord,
    MemoryProjectionCursor,
)
from app.models.room import Player, Room
from app.service.conversation_summary import (
    ConversationSummaryService,
    DeterministicConversationSummaryModel,
    _event_text,
)


async def _create_memory_room(db: AsyncSession, number: int = 1) -> tuple[Room, Player, str]:
    """创建满足 MemoryProjectionCursor 外键的最小可投影房间。"""
    module = await db.scalar(select(ModuleVersion).limit(1))
    assert module is not None
    room_id = f"{number:08d}-0000-0000-0000-000000000001"
    player_id = f"{number:08d}-0000-0000-0000-000000000002"
    actor_id = f"{number:08d}-0000-0000-0000-000000000003"
    room = Room(id=room_id, room_code=f"M{number:04d}", room_name="记忆测试房间", max_players=2)
    player = Player(id=player_id, room_id=room_id, nickname="测试玩家")
    db.add_all(
        [
            room,
            player,
            GameSession(
                room_id=room_id,
                module_id=module.module_id,
                module_version=module.version,
                state_json={"scene_id": "study"},
            ),
        ]
    )
    await db.commit()
    return room, player, actor_id


def _event(
    room_id: str,
    event_id: str,
    created_at: datetime,
    player_id: str,
    actor_id: str,
) -> Event:
    """构造一条玩家可见的公开叙事事件。"""
    return Event(
        id=event_id,
        room_id=room_id,
        player_id=player_id,
        actor_id=actor_id,
        event_type="action.broadcast",
        visibility="public",
        payload={"text": f"调查记录 {event_id}"},
        scene_id="study",
        view_revision="1",
        created_at=created_at,
    )


def test_memory_context_rejects_cross_room_entry() -> None:
    """不同房间的记忆不能进入当前玩家上下文。"""
    entry = MemoryEntry(
        memory_id="m1",
        room_id="room-2",
        subject_id="actor-1",
        kind="conversation",
        content="玩家说过一句话",
        epistemic_status="asserted",
        visibility="player_scoped",
        source_event_id="event-1",
        source_sequence=1,
    )
    with pytest.raises(ValueError, match="room_id"):
        MemoryContext(
            room_id="room-1",
            player_id="player-1",
            actor_id="actor-1",
            as_of_revision="1",
            entries=(entry,),
        )


@pytest.mark.asyncio
async def test_fake_summary_preserves_scope_and_source_cursor() -> None:
    """离线摘要也必须绑定玩家、游标和来源事件。"""
    summary = await DeterministicConversationSummaryModel().summarize(
        room_id="room-1",
        player_id="player-1",
        previous=ConversationSummary(room_id="room-1", player_id="player-1", summary="开场"),
        visible_events=({"id": "event-2", "type": "action.broadcast", "text": "玩家调查了旧宅"},),
        source_revision="7",
        through_event_sequence=2,
    )
    assert summary.room_id == "room-1"
    assert summary.player_id == "player-1"
    assert summary.through_event_sequence == 2
    assert summary.source_event_ids == ("event-2",)
    assert "旧宅" in summary.summary
    assert "玩家声称/行动" in summary.summary


def test_narrator_context_serializes_memory_and_summary() -> None:
    """Narrator 契约必须把记忆字段真正序列化，而不是挂在未知属性上。"""
    memory = MemoryEntry(
        memory_id="m1",
        room_id="room-1",
        subject_id="thomas",
        kind="conversation",
        content="托马斯听到了玩家说的话。",
        epistemic_status="experienced",
        visibility="public",
        listener_ids=("thomas",),
        source_event_id="event-1",
        source_sequence=1,
    )
    context = ActionPlanNarrationContext.model_construct(
        background="背景",
        player_input=SimpleNamespace(room_id="room-1", player_id="p1", actor_id="a1"),
        plan_goal="询问托马斯",
        termination_status="resolved",
        player_view=SimpleNamespace(room_id="room-1", player_id="p1", actor_id="a1"),
        memories=(memory,),
        conversation_summary=ConversationSummary(room_id="room-1", player_id="p1"),
    )
    payload = context.to_json_dict()
    assert payload["memories"][0]["epistemic_status"] == "experienced"
    assert payload["memories"][0]["listener_ids"] == ["thomas"]
    assert payload["conversation_summary"]["player_id"] == "p1"


def test_listener_event_projects_experienced_npc_memory() -> None:
    """只有服务端确认的 listener 才能生成 NPC experienced 记忆。"""
    event = SimpleNamespace(
        id="event-1",
        room_id="room-1",
        actor_id="actor_1",
        player_id="player-1",
        event_type="action.broadcast",
        visibility="public",
        scene_id="study",
        view_revision="2",
        payload={
            "utterance": "告诉托马斯：钟摆停在第三声之后。",
            "speaker_id": "actor_1",
            "listener_ids": ["thomas"],
        },
    )
    entries = _listener_memories(cast(Event, event))
    assert len(entries) == 1
    assert entries[0].subject_id == "thomas"
    assert entries[0].epistemic_status == "experienced"
    assert entries[0].listener_ids == ("thomas",)


def test_listener_projection_skips_unproven_listener() -> None:
    """没有服务端确认听众时，玩家原话不能升级成 NPC 亲历。"""
    event = SimpleNamespace(
        id="event-2",
        actor_id="actor_1",
        event_type="action.broadcast",
        payload={"utterance": "我检查了钟摆。"},
    )
    assert _listener_memories(cast(Event, event)) == ()


def test_single_visible_npc_is_listener_for_direct_you_address() -> None:
    """单 NPC 场景中的“我跟你说/记住”必须生成该 NPC 的亲历记忆。"""
    view = SimpleNamespace(
        scene=SimpleNamespace(
            visible_entities=(
                SimpleNamespace(
                    id="gravedigger", kind="npc", name="守墓人", aliases=()
                ),
            )
        )
    )
    assert _listener_ids_for_utterance(
        "我跟你说：月影钟响三次，记住了", cast(PlayerView, view)
    ) == (
        "gravedigger",
    )


def test_ambiguous_you_address_does_not_pick_one_of_multiple_npcs() -> None:
    """多人场景的模糊“你”不能把秘密错误归给任意 NPC。"""
    view = SimpleNamespace(
        scene=SimpleNamespace(
            visible_entities=(
                SimpleNamespace(id="thomas", kind="npc", name="托马斯", aliases=()),
                SimpleNamespace(id="gravedigger", kind="npc", name="守墓人", aliases=()),
            )
        )
    )
    assert _listener_ids_for_utterance(
        "我跟你说：月影钟响三次，记住了", cast(PlayerView, view)
    ) == ()


def test_summary_reads_broadcast_utterance() -> None:
    """action.broadcast 的 utterance 也必须进入摘要字符和内容输入。"""
    event = SimpleNamespace(
        payload={"utterance": "告诉托马斯钟摆停在第三声之后。"},
    )
    assert _event_text(cast(Event, event)) == "告诉托马斯钟摆停在第三声之后。"


@pytest.mark.asyncio
async def test_projection_is_incremental_and_uses_source_time(
    db_session: AsyncSession,
    memory_store,
) -> None:  # noqa: ANN001
    """长局第二次投影不重扫旧事件，最新公开行动不会被 GameEvent 淹没。"""
    room, player, actor_id = await _create_memory_room(db_session, 11)
    base = datetime(2026, 8, 1, tzinfo=UTC)
    db_session.add_all(
        [
            _event(room.id, str(uuid.uuid4()), base + timedelta(seconds=100), player.id, actor_id),
            *(
                GameEvent(
                    room_id=room.id,
                    sequence=sequence,
                    event_id=str(uuid.uuid4()),
                    client_action_id=f"memory-{sequence}",
                    type="action.inspect",
                    actor_id=actor_id,
                    visibility="public",
                    cause=f"旧权威事件 {sequence}",
                    payload={"text": f"旧权威事件 {sequence}"},
                    created_at=base + timedelta(seconds=sequence),
                )
                for sequence in range(1, 30)
            ),
        ]
    )
    await db_session.commit()

    first = await memory_store.project_room_events(room.id)
    second = await memory_store.project_room_events(room.id)
    assert first.scanned_events == 1
    assert first.scanned_game_events == 29
    assert first.inserted == 30
    assert second.scanned_events == 0
    assert second.scanned_game_events == 0

    context = await memory_store.read_context(
        room_id=room.id,
        player_id=player.id,
        actor_id=actor_id,
        revision="1",
    )
    assert any("调查记录" in entry.content for entry in context.entries)


@pytest.mark.asyncio
async def test_concurrent_projection_is_idempotent(
    db_session: AsyncSession,
    memory_store,
) -> None:  # noqa: ANN001
    """Planner/Narrator 同时首次读取时不会因游标或唯一键竞争而丢记忆。"""
    room, player, actor_id = await _create_memory_room(db_session, 12)
    db_session.add(
        _event(
            room.id,
            str(uuid.uuid4()),
            datetime(2026, 8, 2, tzinfo=UTC),
            player.id,
            actor_id,
        )
    )
    await db_session.commit()

    results = await asyncio.gather(
        memory_store.project_room_events(room.id),
        memory_store.project_room_events(room.id),
    )
    assert sum(result.inserted for result in results) == 1
    async with memory_store._session_factory() as session:  # noqa: SLF001
        count = await session.scalar(
            select(MemoryEntryRecord.id).where(MemoryEntryRecord.room_id == room.id)
        )
        cursor = await session.get(MemoryProjectionCursor, room.id)
    assert count is not None
    assert cursor is not None


@pytest.mark.asyncio
async def test_rebuild_is_repeatable_and_keeps_summary(
    db_session: AsyncSession,
    memory_store,
) -> None:  # noqa: ANN001
    """指定房间完整重建只替换 MemoryEntry，摘要和其他房间不受影响。"""
    room, player, actor_id = await _create_memory_room(db_session, 13)
    other_room, other_player, other_actor = await _create_memory_room(db_session, 14)
    db_session.add_all(
        [
            _event(
                room.id,
                str(uuid.uuid4()),
                datetime(2026, 8, 3, tzinfo=UTC),
                player.id,
                actor_id,
            ),
            _event(
                other_room.id,
                str(uuid.uuid4()),
                datetime(2026, 8, 3, tzinfo=UTC),
                other_player.id,
                other_actor,
            ),
            ConversationSummaryRecord(
                room_id=room.id,
                player_id=player.id,
                summary_json={"summary": "保留摘要"},
            ),
        ]
    )
    await db_session.commit()
    await memory_store.project_room_events(room.id)
    await memory_store.project_room_events(other_room.id)

    first = await memory_store.rebuild_room_events(room.id)
    second = await memory_store.rebuild_room_events(room.id)
    assert first.inserted == second.inserted == 1
    async with memory_store._session_factory() as session:  # noqa: SLF001
        summary = await session.scalar(
            select(ConversationSummaryRecord).where(
                ConversationSummaryRecord.room_id == room.id,
                ConversationSummaryRecord.player_id == player.id,
            )
        )
        other_count = await session.scalar(
            select(MemoryEntryRecord.id).where(MemoryEntryRecord.room_id == other_room.id)
        )
    assert summary is not None
    assert summary.summary_json["summary"] == "保留摘要"
    assert other_count is not None


@pytest.mark.asyncio
async def test_summary_enqueue_preserves_running_lease(
    db_session: AsyncSession,
    memory_store,
) -> None:
    """运行中的摘要任务收到新回合时只推进 pending 游标，不覆盖 lease。"""
    room, player, actor_id = await _create_memory_room(db_session, 15)
    base = datetime(2026, 8, 4, tzinfo=UTC)
    db_session.add_all(
        [
            _event(room.id, str(uuid.uuid4()), base + timedelta(seconds=index), player.id, actor_id)
            for index in range(12)
        ]
    )
    await db_session.commit()
    service = ConversationSummaryService(
        memory_store._session_factory,  # noqa: SLF001
        DeterministicConversationSummaryModel(),
    )
    await service.enqueue_if_needed(room_id=room.id, player_id=player.id)
    async with service._session_factory() as session:  # noqa: SLF001
        record = await session.scalar(
            select(ConversationSummaryRecord).where(
                ConversationSummaryRecord.room_id == room.id,
                ConversationSummaryRecord.player_id == player.id,
            )
        )
        assert record is not None
        record.status = "running"
        record.lease_owner = "worker-1"
        record.lease_expires_at = base + timedelta(hours=1)
        await session.commit()
    db_session.add(
        _event(room.id, str(uuid.uuid4()), base + timedelta(seconds=20), player.id, actor_id)
    )
    await db_session.commit()

    await service.enqueue_if_needed(room_id=room.id, player_id=player.id)
    async with service._session_factory() as session:  # noqa: SLF001
        record = await session.scalar(
            select(ConversationSummaryRecord).where(
                ConversationSummaryRecord.room_id == room.id,
                ConversationSummaryRecord.player_id == player.id,
            )
        )
    assert record is not None
    assert record.status == "running"
    assert record.lease_owner == "worker-1"
    assert record.pending_through_sequence == 13


@pytest.mark.asyncio
async def test_read_context_normalizes_uuid_scope_and_entity_memory(
    db_session: AsyncSession,
    memory_store,
) -> None:  # noqa: ANN001
    """带连字符 UUID 和跨地点 NPC 记忆仍能安全进入当前 Host 上下文。"""
    room, player, actor_id = await _create_memory_room(db_session, 16)
    db_session.add_all(
        [
            Event(
                id=str(uuid.uuid4()),
                room_id=room.id,
                player_id=player.id,
                actor_id=actor_id,
                event_type="action.broadcast",
                visibility="public",
                scene_id="thomas_office",
                payload={
                    "utterance": "告诉托马斯记住蓝色钟摆的三个节拍。",
                    "speaker_id": actor_id,
                    "listener_ids": ["thomas"],
                },
                created_at=datetime(2026, 8, 5, tzinfo=UTC),
            ),
            ConversationSummaryRecord(
                room_id=room.id,
                player_id=player.id,
                summary_json={
                    "room_id": room.id,
                    "player_id": player.id,
                    "summary": "托马斯听过一段重要咒语。",
                },
            ),
        ]
    )
    await db_session.commit()

    context = await memory_store.read_context(
        room_id=room.id,
        player_id=player.id,
        actor_id=actor_id,
        revision="1",
        entity_ids=("thomas",),
        location_id="arnoldsburg_streets",
    )
    assert any(entry.epistemic_status == "experienced" for entry in context.entries)
    assert context.conversation_summary is not None
    assert context.conversation_summary.room_id == room.id
    assert context.conversation_summary.player_id == player.id
