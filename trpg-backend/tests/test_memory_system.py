"""记忆契约、摘要模型和确定性降级的最小回归测试。"""

from types import SimpleNamespace
from typing import cast

import pytest
from collaboration_framework.host.schemas import (
    ActionPlanNarrationContext,
    ConversationSummary,
    MemoryContext,
    MemoryEntry,
)

from app.adapters.sqlalchemy_memory import _listener_memories
from app.models.event import Event
from app.service.conversation_summary import (
    DeterministicConversationSummaryModel,
    _event_text,
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


def test_summary_reads_broadcast_utterance() -> None:
    """action.broadcast 的 utterance 也必须进入摘要字符和内容输入。"""
    event = SimpleNamespace(
        payload={"utterance": "告诉托马斯钟摆停在第三声之后。"},
    )
    assert _event_text(cast(Event, event)) == "告诉托马斯钟摆停在第三声之后。"
