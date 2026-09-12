"""玩家独立对话摘要的持久化任务处理器。"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from collaboration_framework.host.schemas import ConversationSummary
from sqlalchemy import and_, delete, exists, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.conversation_summary import ConversationSummaryModel
from app.adapters.sqlalchemy_memory import _insert_ignore
from app.core.event_text import event_text, payload_ids
from app.models.engine import GameSession
from app.models.event import Event, EventAudience
from app.models.memory import ConversationSummaryReceipt, ConversationSummaryRecord
from app.models.room import Player

logger = structlog.get_logger()
_MAX_ATTEMPTS = 5
_SUMMARY_INPUT_CHAR_LIMIT = 4000
_SUMMARY_PROJECTION_VERSION = 1
_SUMMARY_EVENT_TYPES = (
    "action.broadcast",
    "narration.push",
    "check.result",
    "dialogue.player",
    "dialogue.npc",
)


@dataclass(frozen=True, order=True)
class _EventCursor:
    created_at: datetime
    event_id: str


def _cursor_from_event(event: Event) -> _EventCursor:
    return _EventCursor(event.created_at, event.id)


def _cursor_value(record: ConversationSummaryRecord, prefix: str) -> _EventCursor | None:
    created_at = getattr(record, f"{prefix}_event_created_at", None)
    event_id = getattr(record, f"{prefix}_event_id", None)
    return _EventCursor(created_at, event_id) if created_at is not None and event_id else None


def _scope_ids(value: str) -> tuple[str, ...]:
    try:
        canonical = uuid.UUID(value).hex
    except (ValueError, AttributeError):
        canonical = value
    return tuple(dict.fromkeys((value, canonical)))


def _event_text(event: Event) -> str:
    return event_text(event.event_type, event.payload or {})


def _visible_to(player_id: str):
    return or_(
        Event.visibility == "public",
        and_(Event.visibility == "player_scoped", Event.player_id.in_(_scope_ids(player_id))),
        and_(
            Event.visibility == "scene_scoped",
            exists(
                select(EventAudience.event_id).where(
                    EventAudience.event_id == Event.id,
                    EventAudience.player_id.in_(_scope_ids(player_id)),
                )
            ),
        ),
    )


@dataclass(frozen=True)
class _SummaryChunk:
    event: Event
    start: int
    end: int
    total: int
    text: str

    @property
    def complete(self) -> bool:
        return self.end == self.total

    def model_input(self) -> dict:
        payload = self.event.payload or {}
        return {
            "id": self.event.id,
            "type": self.event.event_type,
            "text": self.text,
            "speaker_id": self.event.actor_id,
            "speaker_name": payload.get("speakerName")
            or payload.get("speaker_name")
            or payload.get("characterName"),
            "player_id": self.event.player_id,
            "listener_ids": payload_ids(payload, "listener_ids", "listenerIds"),
            "participant_ids": payload_ids(payload, "participant_ids", "participantIds"),
            "scene_id": self.event.scene_id,
            "source_revision": self.event.view_revision,
            "epistemic_status": (
                "presentation"
                if self.event.event_type == "narration.push"
                else "confirmed"
                if self.event.event_type == "check.result"
                else "asserted"
            ),
            "text_start": self.start,
            "text_end": self.end,
            "text_complete": self.complete,
        }


def _bounded_summary_events(events: list[Event], offsets: dict[str, int]) -> list[_SummaryChunk]:
    """顺序消费完整原文；单条长事件跨请求分段，成功后才能推进其位置。"""
    selected: list[_SummaryChunk] = []
    remaining = _SUMMARY_INPUT_CHAR_LIMIT
    for event in events:
        text = _event_text(event)
        start = min(offsets.get(event.id, 0), len(text))
        end = min(len(text), start + remaining)
        selected.append(_SummaryChunk(event, start, end, len(text), text[start:end]))
        remaining -= end - start
        if remaining == 0:
            break
    return selected


def _source_revision(
    previous: ConversationSummary | None, batch: list[_SummaryChunk]
) -> str | None:
    revisions = [chunk.event.view_revision for chunk in batch]
    if previous:
        revisions.append(previous.source_revision)
    if not revisions or any(revision is None for revision in revisions):
        return None
    known = [str(revision) for revision in revisions]
    if all(revision.isascii() and revision.isdigit() for revision in known):
        return str(max(map(int, known)))
    return known[0] if len(set(known)) == 1 else None


class DeterministicConversationSummaryModel:
    """Fake provider 的低成本摘要，保证离线测试不依赖真实模型。"""

    async def summarize(self, **kwargs) -> ConversationSummary:  # noqa: ANN003
        previous = kwargs.get("previous")
        events = kwargs.get("visible_events", ())
        lines = []
        for item in events:
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            if item.get("type") in {"action.broadcast", "dialogue.player"}:
                text = f"玩家声称/计划：{text}"
            elif item.get("type") == "dialogue.npc":
                speaker = item.get("speaker_name") or item.get("speaker_id") or "NPC"
                text = f"{speaker}说：{text}"
            lines.append(text)
        text = (previous.summary + "\n" if previous and previous.summary else "") + "\n".join(lines)
        return ConversationSummary(
            room_id=kwargs["room_id"],
            player_id=kwargs["player_id"],
            summary=text[-6000:],
            through_event_sequence=kwargs["through_event_sequence"],
            source_revision=kwargs.get("source_revision"),
            source_event_ids=tuple(str(item["id"]) for item in events if item.get("id")),
        )


class ConversationSummaryService:
    """摘要、来源消费进度与任务租约分别可恢复；失败不影响已完成回合。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        model: ConversationSummaryModel | DeterministicConversationSummaryModel,
    ) -> None:
        self._session_factory = session_factory
        self._model = model
        self._worker_task: asyncio.Task[None] | None = None
        self._recovery_after_player: str | None = None

    async def _visible_events(
        self, session: AsyncSession, *, room_id: str, player_id: str, summary_id: str
    ) -> list[Event]:
        """读取仍未消费完的事件，包含较早创建但较晚提交的来源。"""
        return list(
            (
                await session.scalars(
                    select(Event)
                    .where(
                        Event.room_id == room_id,
                        Event.event_type.in_(_SUMMARY_EVENT_TYPES),
                        _visible_to(player_id),
                        ~exists(
                            select(1).where(
                                ConversationSummaryReceipt.summary_id == summary_id,
                                ConversationSummaryReceipt.event_id == Event.id,
                                ConversationSummaryReceipt.complete.is_(True),
                            )
                        ),
                    )
                    .order_by(Event.created_at, Event.id)
                    .limit(200)
                )
            ).all()
        )

    @staticmethod
    def _advance_cursor(
        record: ConversationSummaryRecord, prefix: str, cursor: _EventCursor
    ) -> None:
        previous = _cursor_value(record, prefix)
        if previous is None or cursor > previous:
            setattr(record, f"{prefix}_event_created_at", cursor.created_at)
            setattr(record, f"{prefix}_event_id", cursor.event_id)

    async def _reset_projection(
        self, session: AsyncSession, record: ConversationSummaryRecord
    ) -> None:
        await session.execute(
            delete(ConversationSummaryReceipt).where(
                ConversationSummaryReceipt.summary_id == record.id
            )
        )
        record.summary_json = {}
        record.through_event_sequence = 0
        record.pending_through_sequence = 0
        record.through_event_created_at = record.pending_event_created_at = None
        record.through_event_id = record.pending_event_id = None
        record.source_revision = None
        record.status = "idle"
        record.attempt_count = 0
        record.next_attempt_at = None
        record.lease_owner = record.lease_expires_at = None
        record.projection_version = _SUMMARY_PROJECTION_VERSION
        await session.flush()
        logger.info(
            "conversation_summary_projection_reset",
            room_id=record.room_id,
            player_id=record.player_id,
        )

    async def enqueue_if_needed(self, *, room_id: str, player_id: str, force: bool = False) -> None:
        """按新正文、事件数量或场景变化入队，锁定记录以保留运行中的租约。"""
        async with self._session_factory() as session:
            await session.execute(
                _insert_ignore(
                    session,
                    ConversationSummaryRecord,
                    [
                        {
                            "id": str(uuid.uuid4()),
                            "room_id": room_id,
                            "player_id": player_id,
                            "summary_json": {},
                            "projection_version": _SUMMARY_PROJECTION_VERSION,
                            "through_event_sequence": 0,
                            "pending_through_sequence": 0,
                            "status": "idle",
                            "attempt_count": 0,
                            "updated_at": datetime.now(UTC),
                        }
                    ],
                    index_elements=("room_id", "player_id"),
                )
            )
            record = await session.scalar(
                select(ConversationSummaryRecord)
                .where(
                    ConversationSummaryRecord.room_id == room_id,
                    ConversationSummaryRecord.player_id == player_id,
                )
                .with_for_update()
            )
            assert record is not None
            upgrading = record.projection_version != _SUMMARY_PROJECTION_VERSION
            if upgrading:
                await self._reset_projection(session, record)
            events = await self._visible_events(
                session, room_id=room_id, player_id=player_id, summary_id=record.id
            )
            if not events:
                await session.commit()
                return
            through = _cursor_value(record, "through")
            previous = await session.get(Event, through.event_id) if through else None
            scenes = [
                event.scene_id
                for event in (([previous] if previous else []) + events)
                if event.scene_id
            ]
            scene_changed = any(a != b for a, b in zip(scenes, scenes[1:], strict=False))
            late_event = bool(
                through and any(_cursor_from_event(event) < through for event in events)
            )
            threshold = (
                len(events) >= 10
                or sum(len(_event_text(event)) for event in events) >= 6000
                or scene_changed
                or late_event
            )
            pending = _cursor_value(record, "pending")
            latest = _cursor_from_event(events[-1])
            target_count = record.through_event_sequence + len(events)
            has_new_work = (
                pending is None
                or latest > pending
                or target_count > record.pending_through_sequence
            )
            if record.status == "failed" and not has_new_work and not force and not upgrading:
                await session.commit()
                return
            if record.status != "running" and not (force or upgrading or threshold):
                await session.commit()
                return
            self._advance_cursor(record, "pending", latest)
            record.pending_through_sequence = max(record.pending_through_sequence, target_count)
            # Polling the same retry must preserve backoff and its attempt count.
            if record.status != "running" and (record.status != "retry" or has_new_work or force):
                record.status = "pending"
                record.next_attempt_at = None
                record.attempt_count = 0
            record.updated_at = datetime.now(UTC)
            await session.commit()
            logger.info(
                "conversation_summary_enqueued",
                room_id=room_id,
                player_id=player_id,
                event_count=len(events),
                scene_changed=scene_changed,
                late_event=late_event,
                status=record.status,
                pending_event_id=record.pending_event_id,
            )

    async def enqueue_room_if_needed(self, *, room_id: str) -> None:
        """逐玩家隔离入队失败；同房其他玩家仍可生成自己的可见摘要。"""
        async with self._session_factory() as session:
            player_ids = list(
                (
                    await session.scalars(
                        select(Player.id).where(Player.room_id == room_id, Player.left_at.is_(None))
                    )
                ).all()
            )
        for player_id in player_ids:
            try:
                await self.enqueue_if_needed(room_id=room_id, player_id=player_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "conversation_summary_enqueue_failed",
                    room_id=room_id,
                    player_id=player_id,
                    error_type=type(exc).__name__,
                )

    async def _claim(self, room_id: str | None, owner: str) -> ConversationSummaryRecord | None:
        now = datetime.now(UTC)
        conditions = [
            or_(
                and_(
                    ConversationSummaryRecord.status.in_(("pending", "retry")),
                    or_(
                        ConversationSummaryRecord.next_attempt_at.is_(None),
                        ConversationSummaryRecord.next_attempt_at <= now,
                    ),
                ),
                and_(
                    ConversationSummaryRecord.status == "running",
                    ConversationSummaryRecord.lease_expires_at <= now,
                ),
            )
        ]
        if room_id is not None:
            conditions.append(ConversationSummaryRecord.room_id == room_id)
        async with self._session_factory() as session:
            candidate = (
                select(ConversationSummaryRecord.id)
                .where(*conditions)
                .order_by(ConversationSummaryRecord.updated_at)
                .limit(1)
                .scalar_subquery()
            )
            # UPDATE rechecks eligibility, including on SQLite where FOR UPDATE is ignored.
            record = (
                await session.execute(
                    update(ConversationSummaryRecord)
                    .where(
                        ConversationSummaryRecord.id == candidate,
                        *conditions,
                    )
                    .values(
                        status="running",
                        lease_owner=owner,
                        lease_expires_at=now + timedelta(minutes=2),
                    )
                    .returning(ConversationSummaryRecord)
                )
            ).scalar_one_or_none()
            await session.commit()
            return record

    async def _fail(self, summary_id: str, owner: str, exc: Exception) -> None:
        async with self._session_factory() as session:
            record = await session.scalar(
                select(ConversationSummaryRecord)
                .where(
                    ConversationSummaryRecord.id == summary_id,
                    ConversationSummaryRecord.lease_owner == owner,
                    ConversationSummaryRecord.status == "running",
                )
                .with_for_update()
            )
            if record:
                record.attempt_count += 1
                record.status = "failed" if record.attempt_count >= _MAX_ATTEMPTS else "retry"
                record.next_attempt_at = (
                    None
                    if record.status == "failed"
                    else datetime.now(UTC) + timedelta(seconds=min(300, 2**record.attempt_count))
                )
                record.lease_owner = record.lease_expires_at = None
                await session.commit()
        logger.warning(
            "conversation_summary_failed", summary_id=summary_id, error_type=type(exc).__name__
        )

    async def process_once(self, *, room_id: str | None = None) -> bool:
        """成功保存摘要时才原子提交消费进度；旧工作者不能覆盖新租约。"""
        owner = str(uuid.uuid4())
        record = await self._claim(room_id, owner)
        if record is None:
            return False
        try:
            return await self._process_claim(record, owner)
        except Exception as exc:  # noqa: BLE001 - includes corrupt saved summaries and database reads
            await self._fail(record.id, owner, exc)
            return False

    async def _process_claim(self, claimed: ConversationSummaryRecord, owner: str) -> bool:
        # Migration may leave a pending old task that the worker claims before reconciliation.
        if claimed.projection_version != _SUMMARY_PROJECTION_VERSION:
            async with self._session_factory() as session:
                record = await session.scalar(
                    select(ConversationSummaryRecord)
                    .where(
                        ConversationSummaryRecord.id == claimed.id,
                        ConversationSummaryRecord.lease_owner == owner,
                    )
                    .with_for_update()
                )
                if record is None:
                    return False
                await self._reset_projection(session, record)
                record.status, record.lease_owner = "running", owner
                record.lease_expires_at = datetime.now(UTC) + timedelta(minutes=2)
                await session.commit()
                claimed = record
        previous = (
            ConversationSummary.model_validate(claimed.summary_json)
            if claimed.summary_json
            else None
        )
        async with self._session_factory() as session:
            events = await self._visible_events(
                session, room_id=claimed.room_id, player_id=claimed.player_id, summary_id=claimed.id
            )
            offset_rows = (
                (
                    await session.execute(
                        select(
                            ConversationSummaryReceipt.event_id,
                            ConversationSummaryReceipt.consumed_chars,
                        ).where(
                            ConversationSummaryReceipt.summary_id == claimed.id,
                            ConversationSummaryReceipt.complete.is_(False),
                        )
                    )
                )
                .tuples()
                .all()
            )
        offsets = dict(offset_rows)
        batch = _bounded_summary_events(events, offsets)
        visible = tuple(chunk.model_input() for chunk in batch if chunk.text)
        completed_count = sum(chunk.complete for chunk in batch)
        source_revision = _source_revision(previous, batch) if batch else claimed.source_revision
        summary = previous
        if visible:
            summary = await self._model.summarize(
                room_id=claimed.room_id,
                player_id=claimed.player_id,
                previous=previous,
                visible_events=visible,
                source_revision=source_revision,
                through_event_sequence=claimed.through_event_sequence + completed_count,
            )
        if summary is not None:
            # All scope, progress and source metadata are owned by the application.
            summary = summary.model_copy(
                update={
                    "room_id": claimed.room_id,
                    "player_id": claimed.player_id,
                    "source_revision": source_revision,
                    "through_event_sequence": claimed.through_event_sequence + completed_count,
                    "source_event_ids": tuple(chunk.event.id for chunk in batch),
                }
            )
        async with self._session_factory() as session:
            record = await session.scalar(
                select(ConversationSummaryRecord)
                .where(
                    ConversationSummaryRecord.id == claimed.id,
                    ConversationSummaryRecord.status == "running",
                    ConversationSummaryRecord.lease_owner == owner,
                )
                .with_for_update()
            )
            if record is None:
                return False
            for chunk in batch:
                receipt = await session.get(ConversationSummaryReceipt, (record.id, chunk.event.id))
                if receipt is None:
                    receipt = ConversationSummaryReceipt(
                        summary_id=record.id, event_id=chunk.event.id
                    )
                    session.add(receipt)
                receipt.consumed_chars, receipt.complete = chunk.end, chunk.complete
            if summary is not None:
                record.summary_json = summary.model_dump(mode="json")
            record.source_revision = source_revision
            record.through_event_sequence = claimed.through_event_sequence + completed_count
            if batch:
                self._advance_cursor(record, "through", _cursor_from_event(batch[-1].event))
            await session.flush()
            # Recheck receipts: late events and replies committed during generation stay pending.
            remaining = await self._visible_events(
                session, room_id=record.room_id, player_id=record.player_id, summary_id=record.id
            )
            record.status = "pending" if remaining else "idle"
            record.pending_through_sequence = record.through_event_sequence + len(remaining)
            if remaining:
                self._advance_cursor(record, "pending", _cursor_from_event(remaining[-1]))
            record.attempt_count = 0
            record.next_attempt_at = None
            record.lease_owner = record.lease_expires_at = None
            record.updated_at = datetime.now(UTC)
            await session.commit()
        logger.info(
            "conversation_summary_saved",
            room_id=claimed.room_id,
            player_id=claimed.player_id,
            event_count=len(batch),
            text_chars=sum(len(chunk.text) for chunk in batch),
            has_remaining=bool(remaining),
        )
        return bool(batch)

    async def rebuild_room(self, room_id: str, *, replace: bool = False) -> tuple[int, int]:
        async with self._session_factory() as session:
            if replace:
                summary_ids = select(ConversationSummaryRecord.id).where(
                    ConversationSummaryRecord.room_id == room_id
                )
                await session.execute(
                    delete(ConversationSummaryReceipt).where(
                        ConversationSummaryReceipt.summary_id.in_(summary_ids)
                    )
                )
                await session.execute(
                    delete(ConversationSummaryRecord).where(
                        ConversationSummaryRecord.room_id == room_id
                    )
                )
            player_ids = list(
                (await session.scalars(select(Player.id).where(Player.room_id == room_id))).all()
            )
            await session.commit()
        for player_id in player_ids:
            await self.enqueue_if_needed(room_id=room_id, player_id=player_id, force=replace)
        generated = 0
        while await self.process_once(room_id=room_id):
            generated += 1
        return len(player_ids), generated

    async def recover_pending(self) -> None:
        """每轮检查一页在场玩家，恢复进程重启、断线或漏排的摘要任务。"""
        async with self._session_factory() as session:
            query = (
                select(Player.room_id, Player.id)
                .join(GameSession, GameSession.room_id == Player.room_id)
                .where(Player.left_at.is_(None))
            )
            if self._recovery_after_player:
                query = query.where(Player.id > self._recovery_after_player)
            players = list((await session.execute(query.order_by(Player.id).limit(100))).all())
        self._recovery_after_player = players[-1][1] if len(players) == 100 else None
        for room_id, player_id in players:
            try:
                await self.enqueue_if_needed(room_id=room_id, player_id=player_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "conversation_summary_recovery_failed",
                    room_id=room_id,
                    player_id=player_id,
                    error_type=type(exc).__name__,
                )

    async def start(self) -> None:
        if self._worker_task is None:
            self._worker_task = asyncio.create_task(self._run(), name="conversation-summary-worker")

    async def stop(self) -> None:
        if self._worker_task is not None:
            self._worker_task.cancel()
            await asyncio.gather(self._worker_task, return_exceptions=True)
            self._worker_task = None

    async def _run(self) -> None:
        next_recovery = 0.0
        while True:
            try:
                now = asyncio.get_running_loop().time()
                if now >= next_recovery:
                    await self.recover_pending()
                    next_recovery = now + 30
                await self.process_once()
            except Exception as exc:  # noqa: BLE001 - a DB/parser failure must not kill the worker
                logger.warning("conversation_summary_worker_failed", error_type=type(exc).__name__)
            await asyncio.sleep(1)


def build_conversation_summary_service(settings, session_factory):  # noqa: ANN001
    """复用 Host provider 构建摘要服务；fake 环境完全离线。"""
    if settings.host_model_provider == "fake":
        model = DeterministicConversationSummaryModel()
    else:
        from app.adapters.deepseek_models import DeepSeekChatCompletionsJsonClient
        from app.adapters.openai_models import OpenAIResponsesJsonClient
        from app.adapters.qwen_models import QwenChatCompletionsJsonClient
        from app.core.config import model_client_retry_policy, secret_value

        if settings.host_model_provider == "deepseek":
            client_type, key, base_url, model_name, timeout = (
                DeepSeekChatCompletionsJsonClient,
                settings.deepseek_api_key,
                settings.deepseek_base_url,
                settings.deepseek_model,
                settings.deepseek_timeout_seconds,
            )
        elif settings.host_model_provider == "qwen":
            client_type, key, base_url, model_name, timeout = (
                QwenChatCompletionsJsonClient,
                settings.qwen_api_key,
                settings.qwen_base_url,
                settings.qwen_model,
                settings.qwen_timeout_seconds,
            )
        else:
            client_type, key, base_url, model_name, timeout = (
                OpenAIResponsesJsonClient,
                settings.openai_api_key,
                settings.openai_base_url,
                settings.openai_model,
                settings.openai_timeout_seconds,
            )
        if key is None:
            raise ValueError("摘要模型缺少 Host provider API key")
        model = ConversationSummaryModel(
            client_type(
                api_key=secret_value(key),
                base_url=base_url,
                model=model_name,
                timeout_seconds=timeout,
                retry_policy=model_client_retry_policy(settings),
            )
        )
    return ConversationSummaryService(session_factory, model)
