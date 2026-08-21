"""长期记忆的确定性投影、权限查询和摘要任务状态存储。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

from collaboration_framework.host.schemas import ConversationSummary, MemoryContext, MemoryEntry
from sqlalchemy import and_, case, delete, or_, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.engine import GameEvent
from app.models.event import Event
from app.models.memory import (
    ConversationSummaryRecord,
    MemoryEntryRecord,
    MemoryProjectionCursor,
)


@dataclass(frozen=True)
class MemoryProjectionResult:
    """描述一次投影处理量和最终高水位，供维护脚本与测试审计。"""

    scanned_events: int
    scanned_game_events: int
    inserted: int
    skipped: int
    event_created_at: datetime | None
    event_id: str | None
    game_sequence: int


def _insert_ignore(
    session: AsyncSession,
    model: Any,
    values: list[dict[str, Any]],
    *,
    index_elements: tuple[str, ...],
) -> Any:
    """使用项目支持的数据库原生冲突忽略，避免并发查重竞态。"""
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(model).values(values)
    elif dialect == "sqlite":
        statement = sqlite_insert(model).values(values)
    else:  # 当前生产和测试只支持 PostgreSQL/SQLite，未知数据库不能静默失去幂等。
        raise RuntimeError(f"unsupported memory projection dialect: {dialect}")
    return statement.on_conflict_do_nothing(index_elements=index_elements)


def _canonical_id(value: str | None) -> str | None:
    """统一 UUID 的连字符表示；非 UUID 的 actor/entity ID 保持原样。"""
    if not value:
        return value
    try:
        return uuid.UUID(value).hex
    except (ValueError, AttributeError):
        return value


def _scope_ids(value: str) -> tuple[str, ...]:
    """查询同时兼容历史带连字符 ID 和新 canonical ID。"""
    canonical = _canonical_id(value) or value
    return tuple(dict.fromkeys((value, canonical)))


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
        subject_id=_canonical_id(event.actor_id or event.player_id) or "room",
        object_id=None,
        kind=kind,
        content=text,
        epistemic_status="presentation" if kind == "conversation" else "asserted",
        visibility="player_scoped" if event.visibility == "player_scoped" else "public",
        participants=tuple(
            canonical
            for x in (event.player_id, event.actor_id)
            if (canonical := _canonical_id(x)) is not None
        ),
        listener_ids=tuple(
            _canonical_id(str(item)) or str(item)
            for item in event.payload.get("listener_ids", event.payload.get("listenerIds", ()))
            if item
        ),
        location_id=event.scene_id,
        source_event_id=event.id,
        source_sequence=0,
        source_revision=event.view_revision,
    )


def _listener_memories(event: Event) -> tuple[MemoryEntry, ...]:
    """把服务端确认的听众投影为 NPC 的亲历记忆，不依赖模型猜测。"""
    if event.event_type != "action.broadcast":
        return ()
    payload = event.payload or {}
    listener_ids = tuple(
        _canonical_id(str(item)) or str(item)
        for item in payload.get("listener_ids", payload.get("listenerIds", ()))
        if item
    )
    utterance = str(payload.get("utterance", "")).strip()
    speaker_id = (
        _canonical_id(
            str(
                payload.get("speaker_id") or payload.get("speakerId") or event.actor_id or ""
            ).strip()
        )
        or ""
    )
    if not listener_ids or not utterance or not speaker_id:
        return ()
    return tuple(
        MemoryEntry(
            memory_id=f"event:{event.id}:listener:{listener_id}",
            room_id=event.room_id,
            subject_id=listener_id,
            object_id=None,
            kind="conversation",
            content=(
                f'玩家角色 {speaker_id} 对实体 {listener_id} 说："{utterance}"；该实体在场并听到。'
            ),
            epistemic_status="experienced",
            visibility="public" if event.visibility == "public" else "player_scoped",
            participants=(speaker_id, listener_id),
            listener_ids=(listener_id,),
            location_id=event.scene_id,
            source_event_id=f"{event.id}:listener:{listener_id}",
            source_sequence=0,
            source_revision=event.view_revision,
        )
        for listener_id in listener_ids
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
        listener_ids=(),
        source_event_id=event.event_id,
        source_sequence=event.sequence,
    )


class SqlAlchemyMemoryStore:
    """提供玩家安全 MemoryContext，并以唯一来源键保证重复投影幂等。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def project_room_events(self, room_id: str) -> MemoryProjectionResult:
        """只投影房间游标后的新事件，并以单事务提交记忆和高水位。"""
        async with self._session_factory() as session:
            result = await self._project_room_events(session, room_id)
            await session.commit()
            return result

    async def rebuild_room_events(self, room_id: str) -> MemoryProjectionResult:
        """在单事务中替换指定房间的记忆投影，保留摘要和权威事件。"""
        async with self._session_factory() as session:
            await session.execute(
                delete(MemoryEntryRecord).where(MemoryEntryRecord.room_id == room_id)
            )
            await session.execute(
                delete(MemoryProjectionCursor).where(MemoryProjectionCursor.room_id == room_id)
            )
            result = await self._project_room_events(session, room_id)
            await session.commit()
            return result

    async def _project_room_events(
        self,
        session: AsyncSession,
        room_id: str,
    ) -> MemoryProjectionResult:
        """在调用方事务内执行投影；数据库唯一键负责跨进程并发幂等。"""
        now = datetime.now(UTC)
        await session.execute(
            _insert_ignore(
                session,
                MemoryProjectionCursor,
                [
                    {
                        "room_id": room_id,
                        "event_created_at": None,
                        "event_id": None,
                        "game_sequence": 0,
                        "updated_at": now,
                    }
                ],
                index_elements=("room_id",),
            )
        )
        cursor = await session.get(MemoryProjectionCursor, room_id)
        if cursor is None:
            raise RuntimeError(f"memory projection cursor missing for room {room_id}")

        event_conditions = [
            Event.room_id == room_id,
            Event.event_type.in_(("action.broadcast", "narration.push", "check.result")),
            or_(Event.visibility == "public", Event.player_id.is_not(None)),
        ]
        if cursor.event_created_at is not None and cursor.event_id is not None:
            event_conditions.append(
                or_(
                    Event.created_at > cursor.event_created_at,
                    and_(
                        Event.created_at == cursor.event_created_at,
                        Event.id > cursor.event_id,
                    ),
                )
            )
        events = list(
            (
                await session.scalars(
                    select(Event).where(*event_conditions).order_by(Event.created_at, Event.id)
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
                        GameEvent.sequence > cursor.game_sequence,
                    )
                    .order_by(GameEvent.sequence)
                )
            ).all()
        )

        candidates: list[tuple[MemoryEntry, datetime]] = []
        for event in events:
            if entry := _memory_from_event(event):
                candidates.append((entry, event.created_at))
            candidates.extend((entry, event.created_at) for entry in _listener_memories(event))
        candidates.extend(
            (entry, event.created_at)
            for event in game_events
            if (entry := _memory_from_game_event(event))
        )
        values = [
            {
                "id": str(uuid.uuid4()),
                "room_id": entry.room_id,
                "subject_id": entry.subject_id,
                "object_id": entry.object_id,
                "kind": entry.kind,
                "content": entry.content,
                "epistemic_status": entry.epistemic_status,
                "visibility": entry.visibility,
                "participants": list(entry.participants),
                "listener_ids": list(entry.listener_ids),
                "location_id": entry.location_id,
                "source_event_id": entry.source_event_id,
                "source_sequence": entry.source_sequence,
                "source_revision": entry.source_revision,
                "source_created_at": source_created_at,
                "created_at": now,
            }
            for entry, source_created_at in candidates
        ]
        inserted = 0
        if values:
            insert_result = cast(
                CursorResult[Any],
                await session.execute(
                    _insert_ignore(
                        session,
                        MemoryEntryRecord,
                        values,
                        index_elements=("room_id", "subject_id", "source_event_id", "kind"),
                    )
                ),
            )
            inserted = max(insert_result.rowcount or 0, 0)

        # 游标更新必须由数据库比较当前值，避免较旧的并发事务覆盖更高水位。
        if events:
            last_event = events[-1]
            await session.execute(
                update(MemoryProjectionCursor)
                .where(
                    MemoryProjectionCursor.room_id == room_id,
                    or_(
                        MemoryProjectionCursor.event_created_at.is_(None),
                        MemoryProjectionCursor.event_created_at < last_event.created_at,
                        and_(
                            MemoryProjectionCursor.event_created_at == last_event.created_at,
                            MemoryProjectionCursor.event_id < last_event.id,
                        ),
                    ),
                )
                .values(
                    event_created_at=last_event.created_at,
                    event_id=last_event.id,
                    updated_at=now,
                )
                .execution_options(synchronize_session=False)
            )
        if game_events:
            await session.execute(
                update(MemoryProjectionCursor)
                .where(
                    MemoryProjectionCursor.room_id == room_id,
                    MemoryProjectionCursor.game_sequence < game_events[-1].sequence,
                )
                .values(game_sequence=game_events[-1].sequence, updated_at=now)
                .execution_options(synchronize_session=False)
            )
        await session.refresh(cursor)
        return MemoryProjectionResult(
            scanned_events=len(events),
            scanned_game_events=len(game_events),
            inserted=inserted,
            skipped=len(candidates) - inserted,
            event_created_at=cursor.event_created_at,
            event_id=cursor.event_id,
            game_sequence=cursor.game_sequence,
        )

    async def read_context(
        self,
        *,
        room_id: str,
        player_id: str,
        actor_id: str,
        revision: str,
        entity_ids: tuple[str, ...] = (),
        location_id: str | None = None,
        limit: int = 12,
        max_chars: int = 4000,
    ) -> MemoryContext:
        """按服务端作用域过滤记忆，模型不能自行扩大查询范围。"""
        await self.project_room_events(room_id)
        async with self._session_factory() as session:
            player_scope_ids = _scope_ids(player_id)
            actor_scope_ids = _scope_ids(actor_id)
            entity_scope_ids = tuple(
                item for entity_id in entity_ids for item in _scope_ids(entity_id)
            )
            conditions = [
                MemoryEntryRecord.room_id == room_id,
                # Engine 的内部裁决原因只服务审计，不应占用 Host 的剧情记忆预算。
                ~MemoryEntryRecord.content.startswith("adjudication:"),
                or_(
                    MemoryEntryRecord.visibility == "public",
                    and_(
                        MemoryEntryRecord.visibility == "player_scoped",
                        or_(
                            *(
                                MemoryEntryRecord.participants.contains([item])
                                for item in player_scope_ids
                            )
                        ),
                    ),
                    MemoryEntryRecord.subject_id.in_(
                        (*player_scope_ids, *actor_scope_ids, *entity_scope_ids)
                    ),
                ),
            ]
            if location_id:
                conditions.append(
                    or_(
                        MemoryEntryRecord.location_id == location_id,
                        MemoryEntryRecord.object_id.in_(entity_scope_ids),
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
                            case(
                                (
                                    MemoryEntryRecord.epistemic_status.in_(
                                        ("experienced", "heard")
                                    ),
                                    0,
                                ),
                                (MemoryEntryRecord.kind == "conversation", 1),
                                (MemoryEntryRecord.epistemic_status == "presentation", 2),
                                else_=3,
                            ),
                            MemoryEntryRecord.source_created_at.desc(),
                            MemoryEntryRecord.source_event_id.desc(),
                            MemoryEntryRecord.id.desc(),
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
                        "listener_ids": tuple(record.listener_ids or ()),
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
                    ConversationSummaryRecord.player_id.in_(player_scope_ids),
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
