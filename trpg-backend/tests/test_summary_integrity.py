"""Exercise summary durability and complete input delivery without external model calls."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.models.event import EventAudience
from app.models.memory import ConversationSummaryReceipt, ConversationSummaryRecord
from app.models.room import Player
from app.service.conversation_summary import (
    ConversationSummaryService,
    DeterministicConversationSummaryModel,
)
from tests.test_memory_integrity import dialogue
from tests.test_memory_system import _create_memory_room


class CaptureSummary(DeterministicConversationSummaryModel):
    def __init__(self):
        self.calls = []

    async def summarize(self, **kwargs):
        self.calls.append(kwargs)
        return await super().summarize(**kwargs)


async def summary_record(service, room, player):
    async with service._session_factory() as session:
        return await session.scalar(
            select(ConversationSummaryRecord).where(
                ConversationSummaryRecord.room_id == room.id,
                ConversationSummaryRecord.player_id == player.id,
            )
        )


async def test_first_scene_change_summarizes_speakers_listeners_and_only_visible_events(
    db_session, memory_store
):
    room, player, actor = await _create_memory_room(db_session, 730)
    other = Player(id=str(uuid.uuid4()), room_id=room.id, nickname="未在场的人")
    question = dialogue(
        room,
        player,
        text="我们一起过去。",
        speaker=actor,
        listeners=("npc",),
        visibility="scene_scoped",
    )
    answer = dialogue(room, player, text="好，一起走。", offset=1)
    answer.payload = {
        **answer.payload,
        "speakerName": "同行者",
        "listenerIds": [actor],
        "participantIds": ["npc", actor],
    }
    arrival = dialogue(room, player, text="你们一起抵达车站。", offset=2)
    arrival.event_type = "narration.push"
    arrival.scene_id = "station"
    private = dialogue(
        room, other, text="不能进入玩家摘要的密谈", visibility="player_scoped", offset=3
    )
    orphan = dialogue(
        room, player, text="无冻结受众的场景话语", visibility="scene_scoped", offset=4
    )
    db_session.add_all(
        [
            other,
            question,
            answer,
            arrival,
            private,
            orphan,
            EventAudience(event_id=question.id, player_id=player.id),
        ]
    )
    await db_session.commit()
    capture = CaptureSummary()
    service = ConversationSummaryService(memory_store._session_factory, capture)
    await service.enqueue_if_needed(room_id=room.id, player_id=player.id)
    assert await service.process_once()
    visible = capture.calls[0]["visible_events"]
    assert [entry["text"] for entry in visible] == [
        "我们一起过去。",
        "好，一起走。",
        "你们一起抵达车站。",
    ]
    assert visible[1]["speaker_id"] == "npc" and visible[1]["speaker_name"] == "同行者"
    assert visible[1]["listener_ids"] == (actor,)
    assert visible[1]["participant_ids"] == ("npc", actor)
    assert visible[1]["epistemic_status"] == "asserted"
    assert visible[2]["scene_id"] == "station"
    record = await summary_record(service, room, player)
    assert record.source_revision == "1" and record.status == "idle"


async def test_long_source_is_delivered_in_full_across_bounded_requests(db_session, memory_store):
    room, player, _ = await _create_memory_room(db_session, 731)
    full = "开场约定" + "正文" * 4500 + "真正的关键尾句"
    source = dialogue(room, player, text=full)
    db_session.add(source)
    await db_session.commit()
    capture = CaptureSummary()
    service = ConversationSummaryService(memory_store._session_factory, capture)
    await service.enqueue_if_needed(room_id=room.id, player_id=player.id)
    assert await service.process_once()
    async with service._session_factory() as session:
        record = await summary_record(service, room, player)
        receipt = await session.get(ConversationSummaryReceipt, (record.id, source.id))
        assert receipt is not None
        assert receipt.consumed_chars == 4000 and not receipt.complete
        assert record.through_event_sequence == 0
    assert await service.process_once()
    assert await service.process_once()
    assert not await service.process_once()
    chunks = [event for call in capture.calls for event in call["visible_events"]]
    assert "".join(chunk["text"] for chunk in chunks) == full
    assert all(
        sum(len(event["text"]) for event in call["visible_events"]) <= 4000
        for call in capture.calls
    )
    assert [chunk["text_start"] for chunk in chunks] == [0, 4000, 8000]
    assert chunks[-1]["text_complete"]
    record = await summary_record(service, room, player)
    assert record.through_event_sequence == 1 and record.status == "idle"
    assert "真正的关键尾句" in record.summary_json["summary"]


async def test_summary_includes_late_committed_event_without_reprocessing_old_events(
    db_session, memory_store
):
    room, player, _ = await _create_memory_room(db_session, 732)
    newest = dialogue(room, player, text="先保存的新事件", offset=10)
    db_session.add(newest)
    await db_session.commit()
    capture = CaptureSummary()
    service = ConversationSummaryService(memory_store._session_factory, capture)
    await service.enqueue_if_needed(room_id=room.id, player_id=player.id, force=True)
    assert await service.process_once()
    late = dialogue(room, player, text="随后提交的较早事件", offset=2)
    db_session.add(late)
    await db_session.commit()
    await service.enqueue_if_needed(room_id=room.id, player_id=player.id)
    assert await service.process_once()
    assert [event["id"] for event in capture.calls[-1]["visible_events"]] == [late.id]
    record = await summary_record(service, room, player)
    assert record.through_event_id == newest.id
    assert "随后提交" in record.summary_json["summary"]
    assert record.through_event_sequence == 2


async def test_concurrent_claim_and_reply_during_generation_keep_complete_progress(
    db_session, memory_store, monkeypatch
):
    room, player, actor = await _create_memory_room(db_session, 733)
    db_session.add(dialogue(room, player, text="开始这一轮", speaker=actor, listeners=("npc",)))
    await db_session.commit()
    capture = CaptureSummary()
    entered, release = asyncio.Event(), asyncio.Event()
    original = capture.summarize

    async def delayed(**kwargs):
        entered.set()
        await release.wait()
        return await original(**kwargs)

    monkeypatch.setattr(capture, "summarize", delayed)
    service = ConversationSummaryService(memory_store._session_factory, capture)
    await service.enqueue_if_needed(room_id=room.id, player_id=player.id, force=True)
    task = asyncio.create_task(service.process_once())
    try:
        await asyncio.wait_for(entered.wait(), 5)
        assert not await service.process_once()  # another worker cannot claim the live lease
        reply = dialogue(room, player, text="这一轮刚刚提交的 NPC 回答", offset=1)
        db_session.add(reply)
        await db_session.commit()
        await service.enqueue_if_needed(room_id=room.id, player_id=player.id)
    finally:
        release.set()
        assert await asyncio.wait_for(task, 5)
    assert (await summary_record(service, room, player)).status == "pending"
    assert await service.process_once()
    assert [event["id"] for event in capture.calls[-1]["visible_events"]] == [reply.id]
    assert (await summary_record(service, room, player)).status == "idle"


async def test_failure_does_not_consume_text_or_reset_backoff_on_poll(db_session, memory_store):
    room, player, _ = await _create_memory_room(db_session, 734)
    source = dialogue(room, player, text="原文" * 3300)
    db_session.add(source)
    await db_session.commit()
    capture = CaptureSummary()
    capture.summarize = AsyncMock(side_effect=ValueError("invalid output"))
    service = ConversationSummaryService(memory_store._session_factory, capture)
    await service.enqueue_if_needed(room_id=room.id, player_id=player.id)
    assert not await service.process_once()
    before = await summary_record(service, room, player)
    assert before.status == "retry" and before.attempt_count == 1
    async with service._session_factory() as session:
        assert await session.get(ConversationSummaryReceipt, (before.id, source.id)) is None
    await service.enqueue_if_needed(room_id=room.id, player_id=player.id)
    after = await summary_record(service, room, player)
    assert after.next_attempt_at == before.next_attempt_at and after.attempt_count == 1
    # Expired lease recovery also goes through the same atomic claim.
    async with service._session_factory() as session:
        saved = await session.get(ConversationSummaryRecord, before.id)
        assert saved is not None
        saved.status = "running"
        saved.lease_owner = "worker-that-exited"
        saved.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
    capture.summarize = AsyncMock(wraps=CaptureSummary.summarize.__get__(capture))
    assert await service.process_once()
    assert capture.calls[0]["visible_events"][0]["text_start"] == 0


async def test_recovery_discovers_missing_tasks_and_worker_survives_errors(
    db_session, memory_store, monkeypatch
):
    room, player, _ = await _create_memory_room(db_session, 735)
    first = dialogue(room, player, text="开始同行")
    next_scene = dialogue(room, player, text="到了新地方", offset=1)
    next_scene.scene_id = "next"
    db_session.add_all([first, next_scene])
    await db_session.commit()
    service = ConversationSummaryService(memory_store._session_factory, CaptureSummary())
    assert await summary_record(service, room, player) is None
    await service.recover_pending()
    assert (await summary_record(service, room, player)).status == "pending"
    assert await service.process_once()

    service.recover_pending = AsyncMock()
    service.process_once = AsyncMock(side_effect=[RuntimeError("temporary DB error"), False])
    sleep_count = 0

    async def tick(_):
        nonlocal sleep_count
        sleep_count += 1
        if sleep_count == 2:
            raise asyncio.CancelledError

    monkeypatch.setattr("app.service.conversation_summary.asyncio.sleep", tick)
    with pytest.raises(asyncio.CancelledError):
        await service._run()
    assert service.process_once.await_count == 2


async def test_empty_task_releases_lease_and_legacy_summary_is_rebuilt(db_session, memory_store):
    room, player, _ = await _create_memory_room(db_session, 736)
    service = ConversationSummaryService(memory_store._session_factory, CaptureSummary())
    await memory_store.enqueue_summary(room_id=room.id, player_id=player.id, through_sequence=1)
    assert not await service.process_once()
    record = await summary_record(service, room, player)
    assert record.status == "idle" and record.lease_owner is None
    source = dialogue(room, player, text="旧版被截掉的尾句现在必须进入摘要")
    db_session.add(source)
    await db_session.commit()
    async with service._session_factory() as session:
        old = await session.get(ConversationSummaryRecord, record.id)
        assert old is not None
        old.projection_version = 0
        old.summary_json = {"summary": "旧格式不完整摘要"}
        old.through_event_created_at, old.through_event_id = source.created_at, source.id
        old.through_event_sequence = 1
        await session.commit()
    await service.enqueue_if_needed(room_id=room.id, player_id=player.id)
    assert await service.process_once()
    record = await summary_record(service, room, player)
    assert record.projection_version == 1
    assert "尾句现在必须" in record.summary_json["summary"]
    assert record.through_event_sequence == 1


async def test_corrupt_saved_summary_is_isolated_from_other_rooms(db_session, memory_store):
    room, player, _ = await _create_memory_room(db_session, 737)
    other, other_player, _ = await _create_memory_room(db_session, 738)
    db_session.add_all(
        [
            dialogue(room, player, text="第一间房"),
            dialogue(other, other_player, text="其他房继续工作"),
        ]
    )
    await db_session.commit()
    service = ConversationSummaryService(memory_store._session_factory, CaptureSummary())
    await service.enqueue_if_needed(room_id=room.id, player_id=player.id, force=True)
    await service.enqueue_if_needed(room_id=other.id, player_id=other_player.id, force=True)
    async with service._session_factory() as session:
        bad = await session.scalar(
            select(ConversationSummaryRecord).where(ConversationSummaryRecord.room_id == room.id)
        )
        assert bad is not None
        bad.summary_json = {"not-a-valid-summary": True}
        await session.commit()
    assert not await service.process_once(room_id=room.id)
    assert await service.process_once(room_id=other.id)
    assert (await summary_record(service, room, player)).status == "retry"
    assert (await summary_record(service, other, other_player)).status == "idle"
