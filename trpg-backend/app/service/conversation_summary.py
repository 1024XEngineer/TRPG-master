"""玩家独立对话摘要的持久化任务处理器。"""

from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from collaboration_framework.host.schemas import ConversationSummary
from sqlalchemy import and_, delete, exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.conversation_summary import ConversationSummaryModel
from app.models.event import Event, EventAudience
from app.models.memory import ConversationSummaryRecord
from app.models.room import Player

logger = structlog.get_logger()

# 达到上限后保留失败状态，后续新事件或全量重建可以再次触发。
_MAX_ATTEMPTS = 5
_SUMMARY_INPUT_CHAR_LIMIT = 4000
_SUMMARY_EVENT_TYPES = (
    "action.broadcast",
    "narration.push",
    "check.result",
    "dialogue.player",
    "dialogue.npc",
)


@dataclass(frozen=True, order=True)
class _EventCursor:
    """摘要使用的稳定 Event 复合游标。"""

    created_at: datetime
    event_id: str


def _cursor_from_event(event: Event) -> _EventCursor:
    """从 Event 取得可跨数据库排序的游标。"""
    return _EventCursor(event.created_at, event.id)


def _cursor_value(record: ConversationSummaryRecord, prefix: str) -> _EventCursor | None:
    """读取新游标；旧迁移尚未回填时返回空并走兼容路径。"""
    created_at = getattr(record, f"{prefix}_event_created_at", None)
    event_id = getattr(record, f"{prefix}_event_id", None)
    if created_at is None or event_id is None:
        return None
    return _EventCursor(created_at, event_id)


def _cursor_after(column_created_at, column_id, cursor: _EventCursor):  # noqa: ANN001
    """构造严格位于复合游标之后的 SQL 条件。"""
    return or_(
        column_created_at > cursor.created_at,
        and_(column_created_at == cursor.created_at, column_id > cursor.event_id),
    )


def _cursor_at_or_before(column_created_at, column_id, cursor: _EventCursor):  # noqa: ANN001
    """构造不超过目标游标的 SQL 条件。"""
    return or_(
        column_created_at < cursor.created_at,
        and_(column_created_at == cursor.created_at, column_id <= cursor.event_id),
    )


def _scope_ids(value: str) -> tuple[str, ...]:
    """摘要查询兼容历史带连字符 UUID 与 canonical UUID。"""
    try:
        canonical = uuid.UUID(value).hex
    except (ValueError, AttributeError):
        canonical = value
    return tuple(dict.fromkeys((value, canonical)))


def _event_text(event: Event) -> str:
    """统一提取摘要可见文本；action.broadcast 使用 utterance 字段。"""
    payload = event.payload or {}
    for key in ("text", "utterance", "summary", "description", "content"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:2000]
    return ""


def _bounded_summary_events(events: list[Event]) -> list[Event]:
    """把一次摘要模型请求限制在 4000 字符，剩余事件留给下一次游标推进。"""
    selected: list[Event] = []
    total_chars = 0
    for event in events:
        event_chars = len(_event_text(event))
        if selected and total_chars + event_chars > _SUMMARY_INPUT_CHAR_LIMIT:
            break
        selected.append(event)
        total_chars += event_chars
    return selected


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
            # Fake 摘要也必须保留主张边界，不能把玩家原话伪装成已确认事实。
            if item.get("type") in {"action.broadcast", "dialogue.player"}:
                text = f"玩家声称/计划：{text}"
            lines.append(text)
        text = (previous.summary + "\n" if previous and previous.summary else "") + "\n".join(
            lines[-10:]
        )
        return ConversationSummary(
            room_id=kwargs["room_id"],
            player_id=kwargs["player_id"],
            summary=text[-6000:],
            through_event_sequence=kwargs["through_event_sequence"],
            source_revision=kwargs.get("source_revision"),
            source_event_ids=tuple(str(item["id"]) for item in events if item.get("id")),
        )


class ConversationSummaryService:
    """领取、重试和保存摘要任务；任务失败不影响已完成回合。"""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        model: ConversationSummaryModel | DeterministicConversationSummaryModel,
    ) -> None:
        self._session_factory = session_factory
        self._model = model
        self._worker_task: asyncio.Task[None] | None = None

    async def _visible_events(
        self,
        session: AsyncSession,
        *,
        room_id: str,
        player_id: str,
        after: _EventCursor | None = None,
        through: _EventCursor | None = None,
    ) -> list[Event]:
        """按 viewer 权限和复合游标读取有限摘要输入。"""
        conditions = [
            Event.room_id == room_id,
            Event.event_type.in_(_SUMMARY_EVENT_TYPES),
            or_(
                Event.visibility == "public",
                and_(
                    Event.visibility == "player_scoped",
                    Event.player_id.in_(_scope_ids(player_id)),
                ),
                and_(
                    Event.visibility == "scene_scoped",
                    exists(
                        select(EventAudience.event_id).where(
                            EventAudience.event_id == Event.id,
                            EventAudience.player_id.in_(_scope_ids(player_id)),
                        )
                    ),
                ),
            ),
        ]
        if after is not None:
            conditions.append(_cursor_after(Event.created_at, Event.id, after))
        if through is not None:
            conditions.append(_cursor_at_or_before(Event.created_at, Event.id, through))
        return list(
            (
                await session.scalars(
                    select(Event).where(*conditions).order_by(Event.created_at, Event.id)
                )
            ).all()
        )

    async def _event_before_cursor(
        self,
        session: AsyncSession,
        *,
        room_id: str,
        player_id: str,
        cursor: _EventCursor,
    ) -> Event | None:
        """读取游标前一条事件，用于识别离开场景触发。"""
        return await session.scalar(
            select(Event)
            .where(
                Event.room_id == room_id,
                Event.event_type.in_(_SUMMARY_EVENT_TYPES),
                or_(
                    Event.visibility == "public",
                    and_(
                        Event.visibility == "player_scoped",
                        Event.player_id.in_(_scope_ids(player_id)),
                    ),
                    and_(
                        Event.visibility == "scene_scoped",
                        exists(
                            select(EventAudience.event_id).where(
                                EventAudience.event_id == Event.id,
                                EventAudience.player_id.in_(_scope_ids(player_id)),
                            )
                        ),
                    ),
                ),
                or_(
                    Event.created_at < cursor.created_at,
                    and_(Event.created_at == cursor.created_at, Event.id < cursor.event_id),
                ),
            )
            .order_by(Event.created_at.desc(), Event.id.desc())
            .limit(1)
        )

    @staticmethod
    def _set_cursor(record: ConversationSummaryRecord, prefix: str, cursor: _EventCursor) -> None:
        """在 ORM 记录中写入摘要复合游标。"""
        setattr(record, f"{prefix}_event_created_at", cursor.created_at)
        setattr(record, f"{prefix}_event_id", cursor.event_id)

    async def enqueue_if_needed(self, *, room_id: str, player_id: str, force: bool = False) -> None:
        """根据可见 dialogue/叙事事件判断是否达到摘要阈值。"""
        async with self._session_factory() as session:
            record = await session.scalar(
                select(ConversationSummaryRecord).where(
                    ConversationSummaryRecord.room_id == room_id,
                    ConversationSummaryRecord.player_id == player_id,
                )
            )
            through_cursor = _cursor_value(record, "through") if record else None
            new_events = await self._visible_events(
                session,
                room_id=room_id,
                player_id=player_id,
                after=through_cursor,
            )
            if through_cursor is None and record and record.through_event_sequence:
                # 旧数据没有复合游标时只在一次迁移/部署窗口内兼容 sequence。
                all_events = await self._visible_events(
                    session, room_id=room_id, player_id=player_id
                )
                new_events = all_events[record.through_event_sequence :]
            if not new_events:
                return
            new_chars = sum(len(_event_text(event)) for event in new_events)
            previous_event = (
                await self._event_before_cursor(
                    session,
                    room_id=room_id,
                    player_id=player_id,
                    cursor=through_cursor,
                )
                if through_cursor
                else None
            )
            scene_changed = bool(
                previous_event
                and any(
                    event.scene_id is not None and event.scene_id != previous_event.scene_id
                    for event in new_events
                )
            )
            latest_cursor = _cursor_from_event(new_events[-1])
            threshold_reached = len(new_events) >= 10 or new_chars >= 6000 or scene_changed
            if record is not None and record.status == "running":
                # 运行中的旧任务保留 lease；只推进 pending 目标，避免覆盖当前工作者。
                self._set_cursor(record, "pending", latest_cursor)
                record.pending_through_sequence = max(
                    record.pending_through_sequence,
                    record.through_event_sequence + len(new_events),
                )
                record.updated_at = datetime.now(UTC)
                await session.commit()
                return
            if not threshold_reached and not force:
                return
            if record is None:
                record = ConversationSummaryRecord(
                    room_id=room_id,
                    player_id=player_id,
                    summary_json={},
                    through_event_sequence=0,
                    pending_through_sequence=len(new_events),
                    status="pending",
                    attempt_count=0,
                    updated_at=datetime.now(UTC),
                )
                self._set_cursor(record, "pending", latest_cursor)
                session.add(record)
            else:
                record.pending_through_sequence = max(
                    record.pending_through_sequence,
                    record.through_event_sequence + len(new_events),
                )
                record.status = "pending"
                pending_cursor = _cursor_value(record, "pending")
                if pending_cursor is None or latest_cursor > pending_cursor:
                    self._set_cursor(record, "pending", latest_cursor)
                record.updated_at = datetime.now(UTC)
            await session.commit()

    async def enqueue_room_if_needed(self, *, room_id: str) -> None:
        """为房间内所有仍在场玩家推进摘要；调用方可放入后台任务。"""
        try:
            async with self._session_factory() as session:
                player_ids = list(
                    (
                        await session.scalars(
                            select(Player.id).where(
                                Player.room_id == room_id,
                                Player.left_at.is_(None),
                            )
                        )
                    ).all()
                )
            for player_id in player_ids:
                await self.enqueue_if_needed(room_id=room_id, player_id=player_id)
        except Exception as exc:  # noqa: BLE001 - 后台入队失败不能影响回合
            logger.warning("conversation_summary_enqueue_failed", error_type=type(exc).__name__)

    async def process_once(self, *, room_id: str | None = None) -> bool:
        """处理一个到期任务，使用短 lease 避免多 worker 重复调用。"""
        owner = str(uuid.uuid4())
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            claim_conditions = [
                or_(
                    and_(
                        ConversationSummaryRecord.status.in_(("pending", "retry")),
                        (ConversationSummaryRecord.next_attempt_at.is_(None))
                        | (ConversationSummaryRecord.next_attempt_at <= now),
                    ),
                    and_(
                        ConversationSummaryRecord.status == "running",
                        ConversationSummaryRecord.lease_expires_at.is_not(None),
                        ConversationSummaryRecord.lease_expires_at <= now,
                    ),
                )
            ]
            if room_id is not None:
                claim_conditions.append(ConversationSummaryRecord.room_id == room_id)
            record = await session.scalar(
                select(ConversationSummaryRecord)
                .where(*claim_conditions)
                .order_by(ConversationSummaryRecord.updated_at)
                .with_for_update()
            )
            if record is None:
                return False
            record.status = "running"
            record.lease_owner = owner
            record.lease_expires_at = now + timedelta(minutes=2)
            await session.commit()
            room_id, player_id = record.room_id, record.player_id
            previous_through = record.through_event_sequence
            through_cursor = _cursor_value(record, "through")
            target_cursor = _cursor_value(record, "pending")
            previous = (
                ConversationSummary.model_validate(record.summary_json)
                if record.summary_json
                else None
            )

        async with self._session_factory() as session:
            events = await self._visible_events(
                session,
                room_id=room_id,
                player_id=player_id,
                after=through_cursor,
                through=target_cursor,
            )
            if through_cursor is None and previous_through:
                all_events = await self._visible_events(
                    session, room_id=room_id, player_id=player_id, through=target_cursor
                )
                events = all_events[previous_through:]
        # 只压缩成功游标之后、当前 pending 目标之前的新事件。
        batch = _bounded_summary_events(events)
        visible = tuple(
            {"id": event.id, "text": _event_text(event), "type": event.event_type}
            for event in batch
        )
        if not visible:
            return False
        resolved_target = _cursor_from_event(batch[-1])
        try:
            summary = await self._model.summarize(
                room_id=room_id,
                player_id=player_id,
                previous=previous,
                visible_events=visible,
                source_revision=None,
                through_event_sequence=previous_through + len(batch),
            )
        except Exception as exc:  # noqa: BLE001 - background failure is recoverable
            async with self._session_factory() as session:
                record = await session.scalar(
                    select(ConversationSummaryRecord).where(
                        ConversationSummaryRecord.room_id == room_id,
                        ConversationSummaryRecord.player_id == player_id,
                        ConversationSummaryRecord.status == "running",
                        ConversationSummaryRecord.lease_owner == owner,
                    )
                )
                if record:
                    record.attempt_count += 1
                    if record.attempt_count >= _MAX_ATTEMPTS:
                        record.status = "failed"
                        record.next_attempt_at = None
                    else:
                        record.status = "retry"
                        record.next_attempt_at = datetime.now(UTC) + timedelta(
                            seconds=min(300, 2 ** min(record.attempt_count, 8))
                        )
                    record.lease_owner = None
                    record.lease_expires_at = None
                    await session.commit()
            logger.warning("conversation_summary_failed", error_type=type(exc).__name__)
            return False

        async with self._session_factory() as session:
            record = await session.scalar(
                select(ConversationSummaryRecord).where(
                    ConversationSummaryRecord.room_id == room_id,
                    ConversationSummaryRecord.player_id == player_id,
                    ConversationSummaryRecord.status == "running",
                    ConversationSummaryRecord.lease_owner == owner,
                )
            )
            if record:
                record.summary_json = summary.model_dump(mode="json")
                record.through_event_sequence = summary.through_event_sequence
                self._set_cursor(record, "through", resolved_target)
                current_pending = _cursor_value(record, "pending")
                record.status = (
                    "pending"
                    if (current_pending is not None and current_pending > resolved_target)
                    or record.pending_through_sequence > summary.through_event_sequence
                    else "idle"
                )
                record.attempt_count = 0
                record.next_attempt_at = None
                record.lease_owner = None
                record.lease_expires_at = None
                record.updated_at = datetime.now(UTC)
                await session.commit()
        return True

    async def rebuild_room(self, room_id: str, *, replace: bool = False) -> tuple[int, int]:
        """按正常摘要代码重建指定房间，并返回玩家数与生成次数。"""
        async with self._session_factory() as session:
            if replace:
                # 显式 replace 只清理该房间摘要，不触碰原始 Event 或 Memory。
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

    async def start(self) -> None:
        """启动轻量轮询；摘要任务自身已持久化，重启可继续。"""
        if self._worker_task is not None:
            return
        self._worker_task = asyncio.create_task(self._run(), name="conversation-summary-worker")

    async def stop(self) -> None:
        if self._worker_task is None:
            return
        self._worker_task.cancel()
        await asyncio.gather(self._worker_task, return_exceptions=True)
        self._worker_task = None

    async def _run(self) -> None:
        while True:
            await self.process_once()
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
