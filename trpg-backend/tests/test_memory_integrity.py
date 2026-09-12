"""End-to-end regressions for the memory integrity audit, using isolated storage."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

from sqlalchemy import select

from app.models.event import Event, EventAudience
from app.models.memory import MemoryEntryRecord
from app.models.room import Player
from tests.test_memory_system import _create_memory_room


def dialogue(room, player, *, text, speaker="npc", listeners=(), visibility="public", offset=0):
    return Event(
        id=str(uuid.uuid4()),
        room_id=room.id,
        player_id=player.id,
        actor_id=speaker,
        event_type="dialogue.player" if listeners else "dialogue.npc",
        visibility=visibility,
        scene_id="old-scene",
        view_revision="1",
        payload={
            "utterance" if listeners else "text": text,
            "speakerId": speaker,
            "listenerIds": list(listeners),
            "participantIds": [speaker, *listeners],
        },
        created_at=datetime(2026, 9, 1, tzinfo=UTC) + timedelta(seconds=offset),
    )


async def read(memory_store, room, player, actor, **kwargs):
    return await memory_store.read_npc_context(
        room_id=room.id,
        player_id=player.id,
        actor_id=actor,
        revision="100",
        entity_ids=("npc",),
        location_id="new-scene",
        **kwargs,
    )


async def test_valid_long_dialogue_preserves_its_tail_and_does_not_block_later_memories(
    db_session, memory_store
):
    room, player, actor = await _create_memory_room(db_session, 710)
    text = "字" * 1990 + "这是原话末尾的重要内容"
    text = text[-2000:]
    db_session.add_all(
        [
            dialogue(room, player, text=text, speaker=actor, listeners=("npc",)),
            dialogue(room, player, text="后续正常回答", offset=1),
        ]
    )
    await db_session.commit()
    for _ in range(2):
        context = await read(memory_store, room, player, actor)
        assert any(text in entry.content for entry in context.entries)
        assert any("后续正常回答" in entry.content for entry in context.entries)
    stored = list(
        (
            await db_session.scalars(
                select(MemoryEntryRecord).where(MemoryEntryRecord.room_id == room.id)
            )
        ).all()
    )
    assert any(text in row.content for row in stored)


async def test_scene_memory_requires_a_frozen_audience(db_session, memory_store):
    room, player, actor = await _create_memory_room(db_session, 711)
    other = Player(id=str(uuid.uuid4()), room_id=room.id, nickname="未在场玩家")
    missing = dialogue(room, player, text="没有冻结受众", visibility="scene_scoped")
    allowed = dialogue(room, player, text="只有在场玩家能读", visibility="scene_scoped", offset=1)
    db_session.add_all(
        [other, missing, allowed, EventAudience(event_id=allowed.id, player_id=player.id)]
    )
    await db_session.commit()
    owner = await read(memory_store, room, player, actor)
    outsider = await read(memory_store, room, other, actor)
    assert [entry.content for entry in owner.entries] == ["只有在场玩家能读"]
    assert not outsider.entries


async def test_projection_refresh_failure_keeps_committed_memories(
    db_session, memory_store, monkeypatch
):
    room, player, actor = await _create_memory_room(db_session, 712)
    db_session.add(dialogue(room, player, text="已经保存的经历"))
    await db_session.commit()
    await memory_store.project_room_events(room.id)
    monkeypatch.setattr(
        memory_store, "project_room_events", AsyncMock(side_effect=ValueError("bad source"))
    )
    context = await read(memory_store, room, player, actor)
    assert [entry.content for entry in context.entries] == ["已经保存的经历"]


async def test_npc_can_recall_another_npc_it_heard_in_a_previous_scene(db_session, memory_store):
    room, player, actor = await _create_memory_room(db_session, 713)
    spoken = dialogue(room, player, text="桥梁已经封闭。", speaker="other-npc")
    spoken.payload = {"text": "桥梁已经封闭。", "listenerIds": ["npc"]}
    db_session.add(spoken)
    await db_session.commit()
    context = await read(memory_store, room, player, actor)
    assert [entry.content for entry in context.entries] == ["桥梁已经封闭。"]
    assert context.entries[0].listener_ids == ("npc",)
    assert context.entries[0].subject_id == "other-npc"


async def test_authoritative_companion_events_are_readable_cross_scene(db_session, memory_store):
    from app.models.engine import GameEvent

    room, player, actor = await _create_memory_room(db_session, 714)
    for sequence, kind, payload in (
        (1, "entity.state_changed", {"entity_id": "npc", "key": "accompanying", "value": True}),
        (
            2,
            "entity.moved",
            {"entity_id": "npc", "location_id": "old-scene", "reason": "accompanying"},
        ),
    ):
        db_session.add(
            GameEvent(
                room_id=room.id,
                sequence=sequence,
                event_id=str(uuid.uuid4()),
                client_action_id="move",
                type=kind,
                actor_id=actor,
                visibility="public",
                cause="adjudication:move",
                payload=payload,
            )
        )
    await db_session.commit()
    context = await read(memory_store, room, player, actor)
    assert len(context.entries) == 2
    assert all(
        "npc" in entry.participants and entry.object_id == "npc" for entry in context.entries
    )
    assert any("一同抵达old-scene" in entry.content for entry in context.entries)
    assert all(not entry.content.startswith("adjudication:") for entry in context.entries)


async def test_structured_check_is_available_to_memory_and_summary(db_session, memory_store):
    from app.service.conversation_summary import _event_text

    room, player, actor = await _create_memory_room(db_session, 715)
    check = dialogue(room, player, text="", speaker=actor, visibility="player_scoped")
    check.event_type = "check.result"
    check.payload = {
        "characterName": "调查员",
        "skillName": "侦查",
        "rollValue": 12,
        "targetValue": 60,
        "successLevel": "hard_success",
    }
    db_session.add(check)
    await db_session.commit()
    context = await memory_store.read_npc_context(
        room_id=room.id, player_id=player.id, actor_id=actor, revision="1", location_id="old-scene"
    )
    assert len(context.entries) == 1
    assert context.entries[0].content == _event_text(check)
    assert "侦查" in context.entries[0].content and "12" in context.entries[0].content


async def test_published_narration_records_current_companions_for_later_recall(
    db_session, memory_store, monkeypatch
):
    import asyncio
    from types import SimpleNamespace

    from collaboration_framework.contracts import PlayerView
    from collaboration_framework.host.schemas import NarrationOutput

    from app.controller import ws

    room, player, actor = await _create_memory_room(db_session, 716)
    view = PlayerView(
        room_id=room.id,
        player_id=player.id,
        actor_id=actor,
        background="公开背景",
        revision="1",
        phase="playing",
        scene_id="old-scene",
        self_actor={"id": actor, "name": "调查员"},
        scene={
            "id": "old-scene",
            "name": "旧站",
            "description": "普通车站",
            "visible_entities": [
                {
                    "id": "npc",
                    "kind": "npc",
                    "name": "同行者",
                    "description": "一同旅行的人",
                    "observable_state": [{"key": "accompanying", "label": "随行", "value": True}],
                },
                {"id": "resident", "kind": "npc", "name": "路人", "description": "偶遇的人"},
            ],
        },
    )
    for name in ("_send_to_player", "_send_view_updated", "_emit_turn_narration"):
        monkeypatch.setattr(ws, name, AsyncMock())
    from app.main import app

    enqueued = asyncio.Event()
    reply_saved = False

    async def persist_followup():
        nonlocal reply_saved
        db_session.add(dialogue(room, player, text="我还跟着你。", offset=1))
        await db_session.commit()
        reply_saved = True

    async def enqueue(**kwargs):
        assert kwargs["room_id"] == room.id
        assert reply_saved, "NPC replies must be committed before summary enqueue"
        enqueued.set()

    monkeypatch.setattr(
        app.state, "conversation_summary_service", SimpleNamespace(enqueue_room_if_needed=enqueue)
    )
    await ws._send_completed_turn_message(
        db_session,
        None,
        room.id,
        player.id,
        actor_id=actor,
        client_action_id="published-companion",
        player_view=view,
        narration=NarrationOutput(kind="narration", text="你和同行者一起走出车站。"),
        after_narration=persist_followup,
    )
    await asyncio.wait_for(enqueued.wait(), 5)
    context = await read(memory_store, room, player, actor)
    assert any("一起走出车站" in item.content for item in context.entries)
    assert "resident" not in context.entries[0].participants


async def test_late_commit_is_projected_without_replaying_processed_events(
    db_session, memory_store
):
    room, player, actor = await _create_memory_room(db_session, 720)
    db_session.add(dialogue(room, player, text="先提交但后发生", offset=10))
    await db_session.commit()
    await memory_store.project_room_events(room.id)
    db_session.add(dialogue(room, player, text="较早创建，稍后才提交", offset=2))
    await db_session.commit()
    result = await memory_store.project_room_events(room.id)
    assert result.scanned_events == 1
    assert result.inserted == 1
    assert (await memory_store.project_room_events(room.id)).scanned_events == 0
    assert {entry.content for entry in (await read(memory_store, room, player, actor)).entries} == {
        "先提交但后发生",
        "较早创建，稍后才提交",
    }


async def test_legacy_projection_is_rebuilt_with_full_text_and_frozen_audience(
    db_session, memory_store
):
    from app.models.memory import MemoryProjectionCursor

    room, player, actor = await _create_memory_room(db_session, 721)
    full = "开头" + "原文" * 1200 + "关键尾句"
    db_session.add_all(
        [
            dialogue(room, player, text=full),
            dialogue(
                room, player, text="不应公开的旧场景记忆", visibility="scene_scoped", offset=1
            ),
        ]
    )
    await db_session.commit()
    await memory_store.project_room_events(room.id)
    records = list(
        (
            await db_session.scalars(
                select(MemoryEntryRecord).where(MemoryEntryRecord.room_id == room.id)
            )
        ).all()
    )
    for entry in records:
        entry.content = entry.content[:2000]
        entry.visibility = "public"
    cursor = await db_session.get(MemoryProjectionCursor, room.id)
    cursor.projection_version = 0
    await db_session.commit()
    context = await read(memory_store, room, player, actor)
    assert [entry.content for entry in context.entries] == [full]
    assert (await memory_store.project_room_events(room.id)).scanned_events == 0


async def test_revision_and_action_boundary_exclude_future_memories_and_summary(
    db_session, memory_store
):
    from collaboration_framework.host.schemas import ConversationSummary

    from app.models.engine import GameSession
    from app.models.memory import ConversationSummaryRecord

    room, player, actor = await _create_memory_room(db_session, 722)
    past = dialogue(room, player, text="行动之前已知", offset=1)
    anchor = dialogue(room, player, text="当前问题", speaker=actor, listeners=("npc",), offset=2)
    anchor.correlation_id = "snapshot:player"
    same_revision_later = dialogue(room, player, text="同版本的后续回答", offset=3)
    future = dialogue(room, player, text="未来事实", offset=4)
    future.view_revision = "8"
    unknown = dialogue(room, player, text="版本不可考的旧记录", offset=0)
    unknown.view_revision = None
    state = await db_session.get(GameSession, room.id)
    state.state_version = 8
    summary = ConversationSummaryRecord(
        room_id=room.id,
        player_id=player.id,
        source_revision="8",
        through_event_created_at=future.created_at,
        through_event_id=future.id,
        summary_json=ConversationSummary(
            room_id=room.id, player_id=player.id, summary="未来摘要", source_revision="8"
        ).model_dump(mode="json"),
    )
    db_session.add_all([past, anchor, same_revision_later, future, unknown, summary])
    await db_session.commit()
    context = await memory_store.read_keeper_context(
        room_id=room.id,
        player_id=player.id,
        actor_id=actor,
        revision="1",
        before_action_id="snapshot",
    )
    assert [entry.content for entry in context.entries] == ["行动之前已知"]
    assert context.conversation_summary is None
    # A summary at the same world revision can still include later dialogue.
    summary.source_revision = "1"
    summary.summary_json = {**summary.summary_json, "source_revision": "1"}
    await db_session.commit()
    context = await memory_store.read_npc_context(
        room_id=room.id,
        player_id=player.id,
        actor_id=actor,
        revision="1",
        before_action_id="snapshot",
    )
    assert context.conversation_summary is None
    latest = await read(memory_store, room, player, actor)
    assert any(entry.content == "未来事实" for entry in latest.entries)


async def test_recent_confirmed_facts_are_not_starved_by_old_dialogue(db_session, memory_store):
    from app.models.engine import GameEvent

    room, player, actor = await _create_memory_room(db_session, 723)
    db_session.add_all(
        [dialogue(room, player, text=f"旧闲谈{index}", offset=index) for index in range(40)]
    )
    db_session.add(
        GameEvent(
            room_id=room.id,
            event_id="confirmed-new",
            sequence=1,
            client_action_id="new-item",
            type="entity.moved",
            actor_id=actor,
            visibility="public",
            cause="adjudication:new-item",
            payload={"entity_id": "key", "holder_actor_id": actor},
            created_at=datetime(2026, 9, 2, tzinfo=UTC),
        )
    )
    await db_session.commit()
    context = await read(memory_store, room, player, actor, limit=2)
    assert context.entries[0].epistemic_status == "confirmed"
    assert context.entries[0].object_id == "key"


async def test_long_memory_uses_marked_excerpt_but_preserves_stored_source(
    db_session, memory_store
):
    room, player, actor = await _create_memory_room(db_session, 724)
    full = "开始约定" + "正文" * 3000 + "最后约定"
    source = dialogue(room, player, text=full)
    db_session.add(source)
    await db_session.commit()
    context = await read(memory_store, room, player, actor, max_chars=100)
    assert len(context.entries) == 1
    entry = context.entries[0]
    assert entry.content_truncated
    assert len(entry.content) == 100
    assert entry.content.startswith("开始约定") and entry.content.endswith("最后约定")
    stored = await db_session.scalar(
        select(MemoryEntryRecord).where(MemoryEntryRecord.room_id == room.id)
    )
    assert stored.content == full
