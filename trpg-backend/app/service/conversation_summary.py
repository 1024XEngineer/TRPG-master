"""玩家独立对话摘要的持久化任务处理器。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import structlog
from collaboration_framework.host.schemas import ConversationSummary
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.adapters.conversation_summary import ConversationSummaryModel
from app.models.event import Event
from app.models.memory import ConversationSummaryRecord
from app.models.room import Player

logger = structlog.get_logger()

# 达到上限后保留失败状态，后续新事件或全量重建可以再次触发。
_MAX_ATTEMPTS = 5


class DeterministicConversationSummaryModel:
    """Fake provider 的低成本摘要，保证离线测试不依赖真实模型。"""

    async def summarize(self, **kwargs) -> ConversationSummary:  # noqa: ANN003
        previous = kwargs.get("previous")
        events = kwargs.get("visible_events", ())
        lines = [str(item.get("text", "")).strip() for item in events if item.get("text")]
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

    async def enqueue_if_needed(self, *, room_id: str, player_id: str) -> None:
        """根据可见事件游标判断是否达到摘要阈值。"""
        async with self._session_factory() as session:
            events = list(
                (
                    await session.scalars(
                        select(Event)
                        .where(
                            Event.room_id == room_id,
                            or_(Event.player_id == player_id, Event.visibility == "public"),
                            Event.event_type.in_(
                                ("action.broadcast", "narration.push", "check.result")
                            ),
                        )
                        .order_by(Event.created_at, Event.id)
                    )
                ).all()
            )
            record = await session.scalar(
                select(ConversationSummaryRecord).where(
                    ConversationSummaryRecord.room_id == room_id,
                    ConversationSummaryRecord.player_id == player_id,
                )
            )
            previous_through = record.through_event_sequence if record else 0
            new_events = events[previous_through:]
            new_chars = sum(len(str(event.payload.get("text", ""))) for event in new_events)
            scene_changed = bool(
                previous_through
                and previous_through < len(events)
                and any(
                    event.scene_id != events[previous_through - 1].scene_id
                    for event in events[previous_through:]
                    if event.scene_id is not None
                )
            )
            if len(events) - previous_through < 10 and new_chars < 6000 and not scene_changed:
                return
            if record is None:
                record = ConversationSummaryRecord(
                    room_id=room_id,
                    player_id=player_id,
                    summary_json={},
                    through_event_sequence=0,
                    pending_through_sequence=len(events),
                    status="pending",
                    attempt_count=0,
                    updated_at=datetime.now(UTC),
                )
                session.add(record)
            else:
                record.pending_through_sequence = len(events)
                record.status = "pending"
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

    async def process_once(self) -> bool:
        """处理一个到期任务，使用短 lease 避免多 worker 重复调用。"""
        owner = str(uuid.uuid4())
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            record = await session.scalar(
                select(ConversationSummaryRecord)
                .where(
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
                    ),
                )
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
            through = record.pending_through_sequence
            previous_through = record.through_event_sequence
            previous = (
                ConversationSummary.model_validate(record.summary_json)
                if record.summary_json
                else None
            )

        async with self._session_factory() as session:
            events = list(
                (
                    await session.scalars(
                        select(Event)
                        .where(
                            Event.room_id == room_id,
                            or_(Event.player_id == player_id, Event.visibility == "public"),
                            Event.event_type.in_(
                                ("action.broadcast", "narration.push", "check.result")
                            ),
                        )
                        .order_by(Event.created_at, Event.id)
                    )
                ).all()
            )
        # 只压缩上次成功游标之后的新事件，避免重复发送整局记录。
        visible = tuple(
            {"id": event.id, "text": event.payload.get("text", ""), "type": event.event_type}
            for event in events[previous_through:through]
        )
        try:
            summary = await self._model.summarize(
                room_id=room_id,
                player_id=player_id,
                previous=previous,
                visible_events=visible,
                source_revision=None,
                through_event_sequence=through,
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
                record.status = "idle"
                record.attempt_count = 0
                record.next_attempt_at = None
                record.lease_owner = None
                record.lease_expires_at = None
                record.updated_at = datetime.now(UTC)
                await session.commit()
        return True

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
