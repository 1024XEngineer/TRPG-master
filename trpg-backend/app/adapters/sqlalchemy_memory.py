"""长期记忆的确定性投影、权限查询和摘要任务状态存储。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from collaboration_framework.host.schemas import ConversationSummary, MemoryContext, MemoryEntry
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.engine import GameEvent
from app.models.event import Event
from app.models.memory import ConversationSummaryRecord, MemoryEntryRecord


def _text(payload: dict) -> str:
    """只抽取玩家安全的展示文本，未知 payload 不升级为事实。"""
    for key in ("text", "utterance", "summary", "description", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:2000]
    return ""


def _memory_from_event(event: Event) -> MemoryEntry | None:
    """把公开行动/叙事事件转换成可审计的 presentation 记忆。"""
    text = _text(event.payload or {})
    if not text:
        return None
    kind = "conversation" if event.event_type == "narration.push" else "action"
    return MemoryEntry(
        memory_id=f"event:{event.id}",
        room_id=event.room_id,
        subject_id=event.actor_id or event.player_id or "room",
        object_id=None,
        kind=kind,
        content=text,
        epistemic_status="presentation" if kind == "conversation" else "asserted",
        visibility="player_scoped" if event.visibility == "player_scoped" else "public",
        participants=tuple(x for x in (event.player_id, event.actor_id) if x),
        location_id=event.scene_id,
        source_event_id=event.id,
        source_sequence=0,
        source_revision=event.view_revision,
    )


def _memory_from_game_event(event: GameEvent) -> MemoryEntry | None:
    """把公开权威事件投影为 confirmed/ex-perienced 记忆。"""
    text = _text(event.payload or {}) or event.cause.strip()
    if not text:
        return None
    if event.type == "location.entered":
        kind = "visit"
    elif "discover" in event.type or "fact" in event.type:
        kind = "clue"
    elif event.type.startswith("action."):
        kind = "action"
    else:
        kind = "world_event"
    return MemoryEntry(
        memory_id=f"game-event:{event.event_id}",
        room_id=event.room_id,
        subject_id=event.actor_id,
        kind=kind,
        content=text[:2000],
        epistemic_status="confirmed",
        visibility="public" if event.visibility == "public" else "entity_scoped",
        participants=(event.actor_id,),
        source_event_id=event.event_id,
        source_sequence=event.sequence,
    )


class SqlAlchemyMemoryStore:
    """提供玩家安全 MemoryContext，并以唯一来源键保证重复投影幂等。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def project_room_events(self, room_id: str) -> int:
        """补投影公开回放事件；规则状态仍由 Engine 自己维护。"""
        async with self._session_factory() as session:
            events = list(
                (
                    await session.scalars(
                        select(Event)
                        .where(
                            Event.room_id == room_id,
                            Event.event_type.in_(
                                ("action.broadcast", "narration.push", "check.result")
                            ),
                            or_(Event.visibility == "public", Event.player_id.is_not(None)),
                        )
                        .order_by(Event.created_at, Event.id)
                    )
                ).all()
            )
            game_events = list(
                (
                    await session.scalars(
                        select(GameEvent)
                        .where(
                            GameEvent.room_id == room_id,
                            GameEvent.visibility == "public",
                        )
                        .order_by(GameEvent.sequence)
                    )
                ).all()
            )
            count = 0
            candidates = [entry for event in events if (entry := _memory_from_event(event))]
            candidates.extend(
                entry for event in game_events if (entry := _memory_from_game_event(event))
            )
            for entry in candidates:
                exists = await session.scalar(
                    select(MemoryEntryRecord.id).where(
                        MemoryEntryRecord.room_id == room_id,
                        MemoryEntryRecord.subject_id == entry.subject_id,
                        MemoryEntryRecord.source_event_id == entry.source_event_id,
                        MemoryEntryRecord.kind == entry.kind,
                    )
                )
                if exists is not None:
                    continue
                session.add(
                    MemoryEntryRecord(
                        id=str(uuid.uuid4()),
                        room_id=entry.room_id,
                        subject_id=entry.subject_id,
                        object_id=entry.object_id,
                        kind=entry.kind,
                        content=entry.content,
                        epistemic_status=entry.epistemic_status,
                        visibility=entry.visibility,
                        participants=list(entry.participants),
                        location_id=entry.location_id,
                        source_event_id=entry.source_event_id,
                        source_sequence=entry.source_sequence,
                        source_revision=entry.source_revision,
                    )
                )
                count += 1
            await session.commit()
            return count

    async def read_context(
        self,
        *,
        room_id: str,
        player_id: str,
        actor_id: str,
        revision: str,
        entity_ids: tuple[str, ...] = (),
        location_id: str | None = None,
        limit: int = 8,
        max_chars: int = 2500,
    ) -> MemoryContext:
        """按服务端作用域过滤记忆，模型不能自行扩大查询范围。"""
        await self.project_room_events(room_id)
        async with self._session_factory() as session:
            conditions = [
                MemoryEntryRecord.room_id == room_id,
                or_(
                    MemoryEntryRecord.visibility == "public",
                    and_(
                        MemoryEntryRecord.visibility == "player_scoped",
                        MemoryEntryRecord.participants.contains([player_id]),
                    ),
                    MemoryEntryRecord.subject_id.in_((player_id, actor_id, *entity_ids)),
                ),
            ]
            if location_id:
                conditions.append(
                    or_(
                        MemoryEntryRecord.location_id == location_id,
                        MemoryEntryRecord.object_id.in_(entity_ids),
                        # 没有地点的全局权威事件仍然是可召回的长期事实；外层
                        # room/visibility/participant 条件继续负责权限隔离。
                        MemoryEntryRecord.location_id.is_(None),
                    )
                )
            records = list(
                (
                    await session.scalars(
                        select(MemoryEntryRecord)
                        .where(*conditions)
                        .order_by(
                            MemoryEntryRecord.source_sequence.desc(),
                            MemoryEntryRecord.created_at.desc(),
                        )
                        .limit(limit * 3)
                    )
                ).all()
            )
            entries: list[MemoryEntry] = []
            total = 0
            for record in records:
                entry = MemoryEntry.model_validate(
                    {
                        "memory_id": record.id,
                        "room_id": record.room_id,
                        "subject_id": record.subject_id,
                        "object_id": record.object_id,
                        "kind": record.kind,
                        "content": record.content,
                        "epistemic_status": record.epistemic_status,
                        "visibility": record.visibility,
                        "participants": tuple(record.participants or ()),
                        "location_id": record.location_id,
                        "source_event_id": record.source_event_id,
                        "source_sequence": record.source_sequence,
                        "source_revision": record.source_revision,
                    }
                )
                if len(entries) >= limit or total + len(entry.content) > max_chars:
                    continue
                entries.append(entry)
                total += len(entry.content)
            summary_record = await session.scalar(
                select(ConversationSummaryRecord).where(
                    ConversationSummaryRecord.room_id == room_id,
                    ConversationSummaryRecord.player_id == player_id,
                )
            )
            summary = None
            if summary_record and summary_record.summary_json:
                summary = ConversationSummary.model_validate(summary_record.summary_json)
            return MemoryContext(
                room_id=room_id,
                player_id=player_id,
                actor_id=actor_id,
                as_of_revision=revision,
                entries=tuple(entries),
                conversation_summary=summary,
            )

    async def enqueue_summary(self, *, room_id: str, player_id: str, through_sequence: int) -> None:
        """推进摘要任务目标；同一玩家只保留最新游标。"""
        async with self._session_factory() as session:
            record = await session.scalar(
                select(ConversationSummaryRecord).where(
                    ConversationSummaryRecord.room_id == room_id,
                    ConversationSummaryRecord.player_id == player_id,
                )
            )
            if record is None:
                record = ConversationSummaryRecord(
                    room_id=room_id,
                    player_id=player_id,
                    summary_json={},
                    pending_through_sequence=through_sequence,
                    status="pending",
                    attempt_count=0,
                    updated_at=datetime.now(UTC),
                )
                session.add(record)
            else:
                record.pending_through_sequence = max(
                    record.pending_through_sequence, through_sequence
                )
                if record.status == "idle":
                    record.status = "pending"
            await session.commit()
