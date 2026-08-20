"""记忆契约、摘要模型和确定性降级的最小回归测试。"""

import pytest
from collaboration_framework.host.schemas import ConversationSummary, MemoryContext, MemoryEntry

from app.service.conversation_summary import DeterministicConversationSummaryModel


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
        visible_events=({"id": "event-2", "text": "玩家调查了旧宅"},),
        source_revision="7",
        through_event_sequence=2,
    )
    assert summary.room_id == "room-1"
    assert summary.player_id == "player-1"
    assert summary.through_event_sequence == 2
    assert summary.source_event_ids == ("event-2",)
    assert "旧宅" in summary.summary
