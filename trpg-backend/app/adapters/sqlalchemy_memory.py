"""长期记忆的确定性投影、权限查询和摘要任务状态存储。"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from typing import cast as typing_cast

import structlog
from collaboration_framework.host.schemas import ConversationSummary, MemoryContext, MemoryEntry
from collaboration_framework.host.schemas.memory import MemoryVisibility
from pydantic import ValidationError
from sqlalchemy import (
    BigInteger,
    String,
    and_,
    case,
    cast,
    delete,
    exists,
    func,
    or_,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.event_text import event_text, game_event_text, payload_ids
from app.models.engine import GameEvent, GameSession
from app.models.event import Event, EventAudience
from app.models.memory import (
    ConversationSummaryRecord,
    MemoryEntryRecord,
    MemoryProjectionCursor,
    MemoryProjectionReceipt,
)

logger = structlog.get_logger()
_PROJECTION_VERSION = 1


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


def _revision_condition(column, revision: str, *, allow_unknown: bool, dialect: str):
    """Only cast validated numeric revisions; opaque revisions must match exactly."""
    numeric = (
        and_(column != "", column.op("NOT GLOB")("*[^0-9]*"), func.length(column) <= 18)
        if dialect == "sqlite"
        else column.op("~")("^[0-9]{1,18}$")
    )
    condition = column == revision
    if revision.isascii() and revision.isdigit():
        condition = or_(
            condition, case((numeric, cast(column, BigInteger)), else_=None) <= int(revision)
        )
    return or_(condition, column.is_(None)) if allow_unknown else condition


def _excerpt(text: str, budget: int) -> str:
    if len(text) <= budget:
        return text
    marker = "…[中段省略]…"
    if budget <= len(marker):
        return text[:budget]
    available = budget - len(marker)
    head = (available + 1) // 2
    return text[:head] + marker + (text[-(available - head) :] if available > head else "")


def _memory_from_event(
    event: Event,
    *,
    audience_player_ids: tuple[str, ...] = (),
) -> MemoryEntry | None:
    """把公开行动/叙事事件转换成可审计的 presentation 记忆。"""
    text = event_text(event.event_type, event.payload or {})
    if not text:
        return None
    if event.event_type in {"narration.push", "dialogue.player", "dialogue.npc"}:
        kind = "conversation"
    else:
        kind = "action"
    if event.event_type == "narration.push":
        epistemic_status = "presentation"
    elif event.event_type == "dialogue.npc":
        epistemic_status = "experienced"
    else:
        epistemic_status = "asserted"
    return MemoryEntry(
        memory_id=f"event:{event.id}",
        room_id=event.room_id,
        subject_id=_canonical_id(event.actor_id or event.player_id) or "room",
        object_id=None,
        kind=kind,
        content=text,
        epistemic_status=epistemic_status,
        visibility=typing_cast(MemoryVisibility, event.visibility),
        participants=tuple(
            canonical
            for x in (
                event.player_id,
                event.actor_id,
                *payload_ids(event.payload or {}, "participant_ids", "participantIds"),
            )
            if (canonical := _canonical_id(x)) is not None
        ),
        listener_ids=tuple(
            _canonical_id(str(item)) or str(item)
            for item in event.payload.get("listener_ids", event.payload.get("listenerIds", ()))
            if item
        ),
        audience_player_ids=audience_player_ids,
        location_id=event.scene_id,
        source_event_id=event.id,
        source_sequence=0,
        source_revision=event.view_revision,
    )


def _listener_memories(
    event: Event,
    *,
    audience_player_ids: tuple[str, ...] = (),
) -> tuple[MemoryEntry, ...]:
    """把服务端确认的听众投影为 NPC 的亲历记忆，不依赖模型猜测。"""
    if event.event_type not in {"action.broadcast", "dialogue.player"}:
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
            visibility=typing_cast(MemoryVisibility, event.visibility),
            participants=(speaker_id, listener_id),
            listener_ids=(listener_id,),
            audience_player_ids=audience_player_ids,
            location_id=event.scene_id,
            source_event_id=f"{event.id}:listener:{listener_id}",
            source_sequence=0,
            source_revision=event.view_revision,
        )
        for listener_id in listener_ids
    )


def _memory_from_game_event(event: GameEvent) -> MemoryEntry | None:
    """把公开权威事件投影为 confirmed/ex-perienced 记忆。"""
    text = game_event_text(event.type, event.payload or {}, event.actor_id)
    if not text:
        return None
    if event.type in {"location.entered", "travel.resolved"}:
        kind = "visit"
    elif event.type == "entity.state_changed" and event.payload.get("key") == "accompanying":
        kind = "relationship_change"
    elif "discover" in event.type or "fact" in event.type or event.type == "information.revealed":
        kind = "clue"
    elif event.type.startswith("action."):
        kind = "action"
    else:
        kind = "world_event"
    return MemoryEntry(
        memory_id=f"game-event:{event.event_id}",
        room_id=event.room_id,
        subject_id=event.actor_id,
        object_id=event.payload.get("entity_id"),
        kind=kind,
        content=text,
        epistemic_status="confirmed",
        visibility="public" if event.visibility == "public" else "entity_scoped",
        participants=tuple(
            dict.fromkeys(
                item
                for item in (
                    event.actor_id,
                    event.payload.get("entity_id"),
                    event.payload.get("holder_actor_id"),
                )
                if isinstance(item, str) and item
            )
        ),
        listener_ids=(),
        audience_player_ids=(),
        source_event_id=event.event_id,
        source_sequence=event.sequence,
        source_revision=str(event.sequence),
        location_id=event.payload.get("location_id") or event.payload.get("destination_id"),
    )


def _event_audience_lookup(rows: list[tuple[str, str]]) -> dict[str, tuple[str, ...]]:
    """把冻结受众行折叠成 event_id -> audience_player_ids 的稳定映射。"""

    audiences: dict[str, list[str]] = {}
    for event_id, player_id in rows:
        audiences.setdefault(event_id, []).append(_canonical_id(player_id) or player_id)
    return {
        event_id: tuple(dict.fromkeys(player_ids)) for event_id, player_ids in audiences.items()
    }


class SqlAlchemyMemoryStore:
    """提供玩家安全 MemoryContext，并以唯一来源键保证重复投影幂等。"""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def project_room_events(self, room_id: str) -> MemoryProjectionResult:
        """投影尚无处理记录的事件，并在同一事务保存记忆和处理记录。"""
        # 房间主键使用数据库中的原始 UUID 文本；canonicalize 只适用于实体参与者。
        async with self._session_factory() as session:
            result = await self._project_room_events(session, room_id)
            await session.commit()
            return result

    async def rebuild_room_events(self, room_id: str) -> MemoryProjectionResult:
        """在单事务中替换指定房间的记忆投影，保留摘要和权威事件。"""
        async with self._session_factory() as session:
            result = await self._project_room_events(session, room_id, force_rebuild=True)
            await session.commit()
            return result

    async def _project_room_events(
        self,
        session: AsyncSession,
        room_id: str,
        *,
        force_rebuild: bool = False,
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
                        "projection_version": _PROJECTION_VERSION,
                        "updated_at": now,
                    }
                ],
                index_elements=("room_id",),
            )
        )
        cursor = await session.scalar(
            select(MemoryProjectionCursor)
            .where(MemoryProjectionCursor.room_id == room_id)
            .with_for_update()
        )
        if cursor is None:
            raise RuntimeError(f"memory projection cursor missing for room {room_id}")

        if force_rebuild or cursor.projection_version != _PROJECTION_VERSION:
            await session.execute(
                delete(MemoryEntryRecord).where(MemoryEntryRecord.room_id == room_id)
            )
            await session.execute(
                delete(MemoryProjectionReceipt).where(MemoryProjectionReceipt.room_id == room_id)
            )
            cursor.event_created_at = None
            cursor.event_id = None
            cursor.game_sequence = 0
            cursor.projection_version = _PROJECTION_VERSION
            await session.flush()
            logger.info("memory_projection_rebuilt", room_id=room_id, version=_PROJECTION_VERSION)

        def unprocessed(kind: str, source_id):
            return ~exists(
                select(1).where(
                    MemoryProjectionReceipt.room_id == room_id,
                    MemoryProjectionReceipt.source_kind == kind,
                    MemoryProjectionReceipt.source_id
                    == (
                        func.replace(cast(source_id, String), "-", "")
                        if kind == "event"
                        else source_id
                    ),
                )
            )

        event_conditions = [
            Event.room_id == room_id,
            Event.event_type.in_(
                (
                    "action.broadcast",
                    "narration.push",
                    "check.result",
                    "dialogue.player",
                    "dialogue.npc",
                )
            ),
            or_(Event.visibility.in_(("public", "scene_scoped")), Event.player_id.is_not(None)),
            unprocessed("event", Event.id),
        ]
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
                        unprocessed("game", GameEvent.event_id),
                    )
                    .order_by(GameEvent.sequence)
                )
            ).all()
        )

        event_audiences: dict[str, tuple[str, ...]] = {}
        if events:
            audience_rows = list(
                (
                    await session.execute(
                        select(EventAudience.event_id, EventAudience.player_id).where(
                            EventAudience.event_id.in_(tuple(event.id for event in events))
                        )
                    )
                ).all()
            )
            event_audiences = _event_audience_lookup(
                [(str(event_id), str(player_id)) for event_id, player_id in audience_rows]
            )

        candidates: list[tuple[MemoryEntry, datetime]] = []
        for event in events:
            if event.visibility == "player_scoped" and event.player_id:
                audience_player_ids = (_canonical_id(event.player_id) or event.player_id,)
            elif event.visibility == "scene_scoped":
                audience_player_ids = event_audiences.get(event.id, ())
            else:
                audience_player_ids = ()
            try:
                if entry := _memory_from_event(event, audience_player_ids=audience_player_ids):
                    candidates.append((entry, event.created_at))
                candidates.extend(
                    (entry, event.created_at)
                    for entry in _listener_memories(event, audience_player_ids=audience_player_ids)
                )
            except (ValidationError, TypeError, ValueError) as exc:
                logger.warning(
                    "memory_event_projection_rejected",
                    room_id=room_id,
                    source_event_id=event.id,
                    error_type=type(exc).__name__,
                )
        for event in game_events:
            try:
                if entry := _memory_from_game_event(event):
                    candidates.append((entry, event.created_at))
            except (ValidationError, TypeError, ValueError) as exc:
                logger.warning(
                    "memory_event_projection_rejected",
                    room_id=room_id,
                    source_event_id=event.event_id,
                    error_type=type(exc).__name__,
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
                "audience_player_ids": list(entry.audience_player_ids),
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
        for offset in range(0, len(values), 100):
            insert_result = typing_cast(
                CursorResult[Any],
                await session.execute(
                    _insert_ignore(
                        session,
                        MemoryEntryRecord,
                        values[offset : offset + 100],
                        index_elements=("room_id", "subject_id", "source_event_id", "kind"),
                    )
                ),
            )
            inserted += max(insert_result.rowcount or 0, 0)

        receipts = [
            {
                "room_id": room_id,
                "source_kind": kind,
                "source_id": source_id.replace("-", "") if kind == "event" else source_id,
            }
            for kind, source_id in (
                *(("event", event.id) for event in events),
                *(("game", event.event_id) for event in game_events),
            )
        ]
        # Bound statement parameters for long-room rebuilds on both SQLite and PostgreSQL.
        for offset in range(0, len(receipts), 300):
            await session.execute(
                _insert_ignore(
                    session,
                    MemoryProjectionReceipt,
                    receipts[offset : offset + 300],
                    index_elements=("room_id", "source_kind", "source_id"),
                )
            )

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
        before_action_id: str | None = None,
        entity_ids: tuple[str, ...] = (),
        location_id: str | None = None,
        limit: int = 12,
        max_chars: int = 4000,
    ) -> MemoryContext:
        """保留旧接口兼容；等价于玩家安全的 NPC 读取路径。"""

        return await self._read_context(
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
            revision=revision,
            before_action_id=before_action_id,
            entity_ids=entity_ids,
            location_id=location_id,
            limit=limit,
            max_chars=max_chars,
            mode="npc",
        )

    async def read_npc_context(
        self,
        *,
        room_id: str,
        player_id: str,
        actor_id: str,
        revision: str,
        before_action_id: str | None = None,
        interlocutor_id: str | None = None,
        entity_ids: tuple[str, ...] = (),
        location_id: str | None = None,
        limit: int = 12,
        max_chars: int = 4000,
    ) -> MemoryContext:
        """给 NPC 回话使用的定向读取：自动把当前交互对象纳入检索范围。"""

        if interlocutor_id is not None:
            entity_ids = tuple(dict.fromkeys((*entity_ids, interlocutor_id)))
        return await self._read_context(
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
            revision=revision,
            before_action_id=before_action_id,
            entity_ids=entity_ids,
            location_id=location_id,
            limit=limit,
            max_chars=max_chars,
            mode="npc",
        )

    async def read_keeper_context(
        self,
        *,
        room_id: str,
        player_id: str,
        actor_id: str,
        revision: str,
        before_action_id: str | None = None,
        entity_ids: tuple[str, ...] = (),
        location_id: str | None = None,
        limit: int = 12,
        max_chars: int = 4000,
    ) -> MemoryContext:
        """Keeper 读取保留 room 级历史，不再按玩家受众收窄。"""

        return await self._read_context(
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
            revision=revision,
            before_action_id=before_action_id,
            entity_ids=entity_ids,
            location_id=location_id,
            limit=limit,
            max_chars=max_chars,
            mode="keeper",
        )

    async def _read_context(
        self,
        *,
        room_id: str,
        player_id: str,
        actor_id: str,
        revision: str,
        before_action_id: str | None = None,
        entity_ids: tuple[str, ...] = (),
        location_id: str | None = None,
        limit: int = 12,
        max_chars: int = 4000,
        mode: str,
    ) -> MemoryContext:
        """共享的有限读取实现；mode 只决定 keeper 是否跳过玩家受众裁剪。"""

        stored_room_id = room_id
        try:
            await self.project_room_events(stored_room_id)
        except (SQLAlchemyError, ValidationError, TypeError, ValueError) as exc:
            # A failed refresh must not discard previously committed memories.
            logger.warning(
                "memory_projection_refresh_failed",
                room_id=room_id,
                error_type=type(exc).__name__,
            )
        async with self._session_factory() as session:

            def array_has(column, item: str):
                if session.get_bind().dialect.name == "sqlite":
                    values = func.json_each(column).table_valued("value")
                    return exists(select(1).select_from(values).where(values.c.value == item))
                return cast(column, JSONB).contains([item])

            def participant_has(item: str):
                return array_has(MemoryEntryRecord.participants, item)

            def audience_has(item: str):
                if session.get_bind().dialect.name == "sqlite":
                    values = func.json_each(MemoryEntryRecord.audience_player_ids).table_valued(
                        "value"
                    )
                    return exists(select(1).select_from(values).where(values.c.value == item))
                return cast(MemoryEntryRecord.audience_player_ids, JSONB).contains([item])

            def audience_empty():
                if session.get_bind().dialect.name == "sqlite":
                    return (
                        func.coalesce(
                            func.json_array_length(MemoryEntryRecord.audience_player_ids),
                            0,
                        )
                        == 0
                    )
                return (
                    func.coalesce(
                        func.jsonb_array_length(cast(MemoryEntryRecord.audience_player_ids, JSONB)),
                        0,
                    )
                    == 0
                )

            head = await session.scalar(
                select(GameSession.state_version).where(GameSession.room_id == room_id)
            )
            allow_unknown = bool(
                revision.isascii() and revision.isdigit() and int(revision) >= (head or 0)
            )
            anchor = None
            if before_action_id:
                anchor = await session.scalar(
                    select(Event)
                    .where(
                        Event.room_id == room_id,
                        Event.event_type.in_(("action.broadcast", "dialogue.player")),
                        Event.correlation_id.in_((before_action_id, before_action_id + ":player")),
                    )
                    .order_by(Event.created_at, Event.id)
                    .limit(1)
                )

            player_scope_ids = _scope_ids(player_id)
            actor_scope_ids = _scope_ids(actor_id)
            entity_scope_ids = tuple(
                item for entity_id in entity_ids for item in _scope_ids(entity_id)
            )
            conditions = [
                MemoryEntryRecord.room_id == stored_room_id,
                ~MemoryEntryRecord.content.startswith("adjudication:"),
                _revision_condition(
                    MemoryEntryRecord.source_revision,
                    revision,
                    allow_unknown=allow_unknown,
                    dialect=session.get_bind().dialect.name,
                ),
            ]
            if anchor is not None:
                # Engine facts from this action are bounded by world revision; presentation
                # history must stop at the input so retries cannot see later same-version dialogue.
                conditions.append(
                    or_(
                        MemoryEntryRecord.source_sequence > 0,
                        MemoryEntryRecord.source_created_at < anchor.created_at,
                    )
                )
            if mode == "npc":
                conditions.append(
                    or_(
                        MemoryEntryRecord.visibility.in_(("public", "scene_scoped")),
                        and_(
                            MemoryEntryRecord.visibility == "player_scoped",
                            or_(*(participant_has(item) for item in player_scope_ids)),
                        ),
                        MemoryEntryRecord.subject_id.in_(
                            (*player_scope_ids, *actor_scope_ids, *entity_scope_ids)
                        ),
                    )
                )
                conditions.append(
                    or_(
                        and_(
                            MemoryEntryRecord.visibility != "scene_scoped",
                            audience_empty(),
                        ),
                        and_(
                            ~audience_empty(),
                            or_(*(audience_has(item) for item in player_scope_ids)),
                        ),
                    )
                )
            if location_id:
                entity_relevance = or_(
                    MemoryEntryRecord.subject_id.in_(entity_scope_ids),
                    MemoryEntryRecord.object_id.in_(entity_scope_ids),
                    *(participant_has(item) for item in entity_scope_ids),
                    *(array_has(MemoryEntryRecord.listener_ids, item) for item in entity_scope_ids),
                )
                conditions.append(
                    or_(
                        MemoryEntryRecord.location_id == location_id,
                        entity_relevance,
                        MemoryEntryRecord.location_id.is_(None),
                    )
                )
            records = list(
                (
                    await session.scalars(
                        select(MemoryEntryRecord)
                        .where(*conditions)
                        .order_by(
                            MemoryEntryRecord.source_created_at.desc(),
                            case((MemoryEntryRecord.epistemic_status == "confirmed", 0), else_=1),
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
                try:
                    entry = MemoryEntry.model_validate(
                        {
                            "memory_id": record.id,
                            "room_id": room_id,
                            "subject_id": record.subject_id,
                            "object_id": record.object_id,
                            "kind": record.kind,
                            "content": record.content,
                            "epistemic_status": record.epistemic_status,
                            "visibility": record.visibility,
                            "participants": tuple(record.participants or ()),
                            "listener_ids": tuple(record.listener_ids or ()),
                            "audience_player_ids": tuple(record.audience_player_ids or ()),
                            "location_id": record.location_id,
                            "source_event_id": record.source_event_id,
                            "source_sequence": record.source_sequence,
                            "source_revision": record.source_revision,
                        }
                    )
                except ValidationError as exc:
                    logger.warning(
                        "memory_record_rejected",
                        room_id=room_id,
                        memory_id=record.id,
                        error_type=type(exc).__name__,
                    )
                    continue
                if len(entries) >= limit or total >= max_chars:
                    break
                # The final entry may be an explicitly marked excerpt, never silently dropped.
                remaining = max_chars - total
                if len(entry.content) > remaining:
                    entry = entry.model_copy(
                        update={
                            "content": _excerpt(entry.content, remaining),
                            "content_truncated": True,
                        }
                    )
                entries.append(entry)
                total += len(entry.content)
            summary_record = await session.scalar(
                select(ConversationSummaryRecord).where(
                    ConversationSummaryRecord.room_id == stored_room_id,
                    ConversationSummaryRecord.projection_version == 1,
                    ConversationSummaryRecord.player_id.in_(player_scope_ids),
                    _revision_condition(
                        ConversationSummaryRecord.source_revision,
                        revision,
                        allow_unknown=allow_unknown,
                        dialect=session.get_bind().dialect.name,
                    ),
                )
            )
            summary = None
            if (
                summary_record
                and anchor is not None
                and (
                    summary_record.through_event_created_at is None
                    or summary_record.through_event_created_at >= anchor.created_at
                )
            ):
                summary_record = None
            if summary_record and summary_record.summary_json:
                summary_payload = dict(summary_record.summary_json)
                summary_payload["room_id"] = room_id
                summary_payload["player_id"] = player_id
                try:
                    summary = ConversationSummary.model_validate(summary_payload)
                    if (
                        summary.source_revision
                        and summary.source_revision.isdigit()
                        and revision.isdigit()
                        and int(summary.source_revision) > int(revision)
                    ):
                        summary = None
                except ValidationError as exc:
                    logger.warning(
                        "memory_summary_rejected", room_id=room_id, error_type=type(exc).__name__
                    )
            logger.info(
                "memory_context_selected",
                room_id=room_id,
                player_id=player_id,
                actor_id=actor_id,
                action_id=before_action_id,
                mode=mode,
                revision=revision,
                entry_count=len(entries),
                text_chars=total,
                source_event_ids=[entry.source_event_id for entry in entries],
                has_summary=summary is not None,
            )
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
