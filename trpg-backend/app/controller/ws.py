"""顶层 `/ws/{roomId}` WebSocket 路由。

故意不挂在 `/api/v1` 前缀下——前端约定的连接地址是
`ws://host/ws/{roomId}?token={token}`，是独立于 REST API 版本号的实时通道，
`roomId` 是房间内部 ID（不是玩家分享用的 roomCode）。

协议：
- 客户端发送 `{type, playerId, payload}`；
- 常规服务端事件使用 `{type, payload}`；
- 动作完成事件直接使用协作框架的
  `{protocol_version, message_type: "turn.completed", correlation_id, payload}`；
- 连接后第一条消息必须是 `room.join`，成功后回 `session.bound`，
  在此之前收到的其它事件类型会被忽略（还没确认这个连接对应哪个玩家）；
- `player.ready`/`game.start`/`action.plan.submit` 使用服务端权威状态，并在房间
  阶段或玩家状态变化后广播 `room.state`；
- `action.plan.submit` 必须携带 `clientActionId`，由 ActionPlanTurnApplication
  完成身份绑定、编排、幂等去重和 PlayerView 投影；框架回包只发给动作发起者，
  `narration.push`（含澄清问话）广播全房间；
- 需要检定时由 ActionPlan 暂停并下发待决策载荷；玩家用 `adjudication.select`
  选技能、`adjudication.post_roll` 处理奖惩骰与孤注一掷，随后计划继续推进。
  旧的 `action.submit`/`check.roll` 单动作通道已随 Checkpoint 运行时一并移除
  （#226：仅面向 ModuleContent v3，不保留兼容层）。
- `san.check.roll`/`room.rejoin` 仍是 `NOT_IMPLEMENTED` 协议桩。
- 每条实际发送的 `narration.push` 都会同步写一行 `events` 表；动作叙事用
  `clientActionId` 做持久化去重，`GET /rooms/{roomId}/replay` 直接读它。
- 落库去重成功后、发出权威 `narration.push` 之前，同一条叙事会先按句切成
  `narration.chunk` 下发用于渐进展示（issue #203）。片段不落库、不构成权威
  历史，拼接结果与最终 `narration.push` 完全一致。

数据库会话按"每条消息一个短 session"处理，而不是整条连接复用一个：一个
WebSocket 可能存活很久，用一个 session 包住整条连接会在这期间一直占着一个
数据库连接/事务，跟并发的 HTTP 请求争抢 SQLite 的锁（测试里表现为死锁）。
鉴权单独用一个短 session，之后每条消息各开各的，消息之间等待时不持有连接。
连接取消时短 session 的 close/rollback 会在 shield 中完成，避免遗留锁。
"""

import asyncio
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from functools import partial
from typing import Literal, cast

import anyio
import structlog
from collaboration_framework.contracts import (
    TERMINAL_ADJUDICATION_STATUSES,
    ActorBindingError,
    AdjudicationExecution,
    AdjudicationValidationError,
    CancelCheckChoice,
    CheckDecisionRequest,
    ContractError,
    GetAdjudicationStatusRequest,
    PlayerInput,
    PlayerView,
    PostRollDecisionRequest,
    PushAdjudication,
    SelectCheckChoice,
)
from collaboration_framework.engine import RevisionConflictError
from collaboration_framework.host.application import (
    TurnExecutionError,
    normalize_narration_text,
    split_narration_chunks,
)
from collaboration_framework.host.schemas import NarrationOutput, reservation_is_expired
from collaboration_framework.host.schemas.action_plan import ActionPlanNpcReply
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from app.adapters import (
    DeepSeekChatCompletionsJsonClient,
    OpenAIResponsesJsonClient,
    PromptHostEntryModel,
    QwenChatCompletionsJsonClient,
)
from app.adapters.structured_http import StructuredOutputError, is_transient_model_error
from app.core.action_plan_turn import (
    ActionPlanTurnResult,
    _matching_visible_entity_ids,
    action_plan_turn_application,
)
from app.core.config import get_settings, model_client_retry_policy, secret_value
from app.core.db import async_session_factory
from app.core.engine import adjudication_engine_service, legacy_single_action_recovery
from app.core.host_entry import (
    DeterministicHostEntryModel,
    HostEntryRouter,
    HostPublicContextProjector,
    HostPublicHistoryEntry,
)
from app.core.turn import (
    ActorResolutionError,
    session_view_application,
)
from app.core.turn_events import (
    TurnEvent,
    TurnFailed,
    TurnPhase,
    TurnPhaseChanged,
    TurnStarted,
    TurnToolCompleted,
    TurnToolStarted,
)
from app.core.turn_observability import (
    log_action_plan_latency,
    log_check_result,
    log_narration_output,
    log_player_input,
    log_turn_failed,
)
from app.dto.ws import (
    ActionBroadcastPayload,
    ActionPlanCancelPayload,
    ActionRecipientPayload,
    ActionSubmitPayload,
    AdjudicationChoicePayload,
    AdjudicationPendingPayload,
    AdjudicationPostRollPayload,
    ChatMessagePayload,
    ChatSendPayload,
    CheckResultPayload,
    ClientEnvelope,
    DialogueNpcPayload,
    DialoguePlayerPayload,
    ErrorPayload,
    GameStartPayload,
    NarrationChunkPayload,
    NarrationPushPayload,
    OpeningStartedPayload,
    PlanProgressPayload,
    PlayerReadyPayload,
    RoomActionStatePayload,
    RoomJoinPayload,
    RoomRejoinPayload,
    SanCheckRollPayload,
    SceneTransitionPendingPayload,
    SceneTransitionResolvedPayload,
    SceneTransitionRespondPayload,
    ServerEnvelope,
    SessionBoundPayload,
    TimeAdvancePendingPayload,
    TimeAdvanceResolvedPayload,
    TimeAdvanceRespondPayload,
    ToolCompletedPayload,
    ToolStartedPayload,
    TurnFailedPayload,
    TurnPhaseChangedPayload,
    TurnStartedPayload,
    ViewUpdatedPayload,
)
from app.models.engine import (
    ActionPlanRunRecord,
    GameSession,
    RoomActionReservation,
    SceneTransitionProposalRecord,
    TimeAdvanceProposalRecord,
)
from app.models.event import Event
from app.models.room import Player
from app.service import auth as auth_service
from app.service import chat as chat_service
from app.service import host_action_queue as host_action_queue_service
from app.service import room as room_service
from app.service import scene_transition as scene_transition_service
from app.service import time_advance as time_advance_service
from app.service.action_lock import action_lock_manager
from app.service.host_action_queue import HostActionQueueError
from app.service.npc_dialogue import (
    npc_dialogue_service,
    require_dialogue_npc,
    visible_dialogue_npcs,
)
from app.service.time_advance import ConsentAwareAdjudicationEngine
from app.service.ws_events import broadcast_room_state
from app.service.ws_manager import manager

router = APIRouter()
logger = structlog.get_logger()

_DIRECT_SPEECH_MARKERS = ("告诉", "询问", "问", "提醒", "威胁", "喊", "说", "请")


def _listener_ids_for_utterance(utterance: str, player_view: PlayerView) -> tuple[str, ...]:
    """只根据明确点名和当前 PlayerView 确定听众，不猜测自然语言意图。"""
    if not any(marker in utterance for marker in _DIRECT_SPEECH_MARKERS):
        return ()
    return _matching_visible_entity_ids(utterance, player_view)


_UNAUTHORIZED_CLOSE_CODE = 4401
_NOT_FOUND_CLOSE_CODE = 4404
_OPENING_MESSAGE_ID = "game-opening"
_HOST_QUEUE_TERMINAL = frozenset({"failed", "cancelled", "discarded"})

_host_entry_router: HostEntryRouter | None = None


def _get_host_entry_router() -> HostEntryRouter:
    """Build the A1 router lazily so test imports stay offline-safe."""

    global _host_entry_router
    if _host_entry_router is not None:
        return _host_entry_router
    settings = get_settings()
    if settings.host_model_provider == "fake":
        model = DeterministicHostEntryModel()
    else:
        client_type = {
            "openai": OpenAIResponsesJsonClient,
            "qwen": QwenChatCompletionsJsonClient,
            "deepseek": DeepSeekChatCompletionsJsonClient,
        }[settings.host_model_provider]
        if settings.host_model_provider == "openai":
            api_key, base_url, model_name, timeout = (
                settings.openai_api_key,
                settings.openai_base_url,
                settings.openai_model,
                settings.openai_timeout_seconds,
            )
        elif settings.host_model_provider == "qwen":
            api_key, base_url, model_name, timeout = (
                settings.qwen_api_key,
                settings.qwen_base_url,
                settings.qwen_model,
                settings.qwen_timeout_seconds,
            )
        else:
            api_key, base_url, model_name, timeout = (
                settings.deepseek_api_key,
                settings.deepseek_base_url,
                settings.deepseek_model,
                settings.deepseek_timeout_seconds,
            )
        if api_key is None:
            raise ValueError("Host entry model provider 缺少 API key")
        model = PromptHostEntryModel(
            client_type(
                api_key=secret_value(api_key),
                base_url=base_url,
                model=model_name,
                timeout_seconds=timeout,
                retry_policy=model_client_retry_policy(settings),
            )
        )
    _host_entry_router = HostEntryRouter(model)
    return _host_entry_router


async def _public_host_history(
    db: AsyncSession,
    room_id: str,
    *,
    exclude_correlation_id: str | None = None,
    max_turns: int = 6,
    max_chars: int = 6000,
) -> tuple[HostPublicHistoryEntry, ...]:
    rows = await db.scalars(
        select(Event)
        .where(
            Event.room_id == room_id,
            Event.event_type.in_(
                ("action.broadcast", "dialogue.player", "dialogue.npc", "narration.push")
            ),
            # HostEntry direct responses are always public.  Do not let a
            # viewer-specific scene_scoped event influence text that will be
            # broadcast to every player in the room.
            Event.visibility == "public",
            *(
                [Event.correlation_id != exclude_correlation_id]
                if exclude_correlation_id is not None
                else []
            ),
        )
        .order_by(Event.created_at.desc(), Event.id.desc())
        .limit(max_turns * 3)
    )
    entries: list[HostPublicHistoryEntry] = []
    for event in reversed(list(rows)):
        text = None
        if isinstance(event.payload, dict):
            text = event.payload.get("text") or event.payload.get("utterance")
        if not isinstance(text, str) or not text.strip():
            continue
        source = cast(
            Literal[
                "player_message",
                "npc_dialogue",
                "keeper_narration",
                "direct_response",
            ],
            {
                "action.broadcast": "player_message",
                "dialogue.player": "player_message",
                "dialogue.npc": "npc_dialogue",
                "narration.push": "keeper_narration",
            }[event.event_type],
        )
        speaker = None
        if isinstance(event.payload, dict):
            speaker = event.payload.get("speakerName") or event.payload.get("characterName")
        entries.append(HostPublicHistoryEntry(source=source, speaker=speaker, text=text.strip()))
    entries = entries[-max_turns:]
    while entries and sum(len(item.text) for item in entries) > max_chars:
        entries.pop(0)
    return tuple(entries)


async def _current_room_action_state(
    db: AsyncSession,
    room_id: str,
) -> RoomActionStatePayload | None:
    """合并持久化 ActionPlan 与短暂进程锁，生成可在重连时重放的行动状态。"""

    session = await db.get(GameSession, room_id)
    if session is None:
        return None
    queued = await host_action_queue_service.list_queued(db, room_id)
    reservation = await db.get(RoomActionReservation, room_id)
    if reservation is not None and not reservation_is_expired(reservation.updated_at):
        active = await db.get(
            ActionPlanRunRecord,
            (room_id, reservation.parent_action_id),
        )
    else:
        active = None
    if active is not None and active.status not in {
        "needs_clarification",
        "retryable_failure",
    }:
        waiting = active.status in {
            "waiting_for_player",
            "awaiting_time_consent",
            "awaiting_scene_consent",
        }
        return RoomActionStatePayload(
            status="awaiting_player" if waiting else "processing",
            player_id=active.player_id,
            actor_id=active.actor_id,
            client_action_id=active.parent_action_id,
            started_at=active.created_at,
            revision=str(session.state_version),
            queued=queued,
        )
    # 单动作不会创建 ActionPlanRun；此时由持久化时间提案继续占有房间行动槽。
    # approved 且叙事未落库表示最后一票已提交、原行动正在恢复，不可提前显示 idle。
    time_proposal = await db.scalar(
        select(TimeAdvanceProposalRecord)
        .where(
            TimeAdvanceProposalRecord.room_id == room_id,
            TimeAdvanceProposalRecord.status.in_(("pending", "approved")),
            TimeAdvanceProposalRecord.narration_persisted.is_(False),
        )
        .order_by(TimeAdvanceProposalRecord.created_at.desc())
        .limit(1)
    )
    if time_proposal is not None:
        actor_id = time_proposal.adjudication_json.get("actor_id")
        if not isinstance(actor_id, str) or not actor_id:
            raise ContractError("时间提案缺少行动 Actor")
        return RoomActionStatePayload(
            status=("awaiting_player" if time_proposal.status == "pending" else "processing"),
            player_id=time_proposal.player_id,
            actor_id=actor_id,
            client_action_id=time_proposal.parent_action_id,
            started_at=time_proposal.created_at,
            revision=str(session.state_version),
            queued=queued,
        )
    scene_proposal = await db.scalar(
        select(SceneTransitionProposalRecord)
        .where(
            SceneTransitionProposalRecord.room_id == room_id,
            SceneTransitionProposalRecord.status.in_(("pending", "approved")),
            SceneTransitionProposalRecord.narration_persisted.is_(False),
        )
        .order_by(SceneTransitionProposalRecord.created_at.desc())
        .limit(1)
    )
    if scene_proposal is not None:
        actor_id = scene_proposal.adjudication_json.get("actor_id")
        if not isinstance(actor_id, str) or not actor_id:
            raise ContractError("场景提案缺少行动 Actor")
        return RoomActionStatePayload(
            status=("awaiting_player" if scene_proposal.status == "pending" else "processing"),
            player_id=scene_proposal.player_id,
            actor_id=actor_id,
            client_action_id=scene_proposal.parent_action_id,
            started_at=scene_proposal.created_at,
            revision=str(session.state_version),
            queued=queued,
        )
    snapshot = action_lock_manager.snapshot(room_id)
    if snapshot is not None:
        return RoomActionStatePayload(
            status="processing",
            player_id=snapshot.player_id,
            actor_id=snapshot.actor_id,
            client_action_id=snapshot.client_action_id,
            started_at=snapshot.started_at,
            revision=str(session.state_version),
            queued=queued,
        )
    return RoomActionStatePayload(
        status="idle",
        revision=str(session.state_version),
        queued=queued,
    )


async def _broadcast_room_action_state(
    db: AsyncSession,
    room_id: str,
    *,
    force_processing: bool = False,
) -> None:
    """广播完整快照而非增量，使丢包和重连都能直接覆盖客户端状态。"""

    state = await _current_room_action_state(db, room_id)
    if state is None:
        return
    if force_processing and state.status != "idle":
        # ActionPlan 在处理玩家回复时仍持久化为 waiting；短暂执行态只用于 UI，
        # 不额外写库，崩溃后仍从权威等待状态恢复。
        state = state.model_copy(update={"status": "processing"})
    envelope = ServerEnvelope(
        type="room.action.state",
        payload=state.model_dump(by_alias=True, mode="json"),
    )
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))


async def _broadcast_room_action_state_fresh(room_id: str) -> None:
    """在原消息事务已被断线取消时，用独立短会话完成最终 idle 广播。"""

    async with async_session_factory() as db:
        await _broadcast_room_action_state(db, room_id)


async def _send_room_action_state(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
) -> None:
    """在玩家加入时单播当前行动状态，恢复处理中或等待玩家的界面。"""

    state = await _current_room_action_state(db, room_id)
    if state is None:
        return
    await _send_to_player(
        websocket,
        ServerEnvelope(
            type="room.action.state",
            payload=state.model_dump(by_alias=True, mode="json"),
        ).model_dump(by_alias=True),
    )


_OWN_WAITING_STATUSES = {
    "waiting_for_player",
    "awaiting_time_consent",
    "awaiting_scene_consent",
}
_OWN_SUPERSEDE_STATUSES = {"needs_clarification", "retryable_failure"}
_host_drain_locks: dict[tuple[int, str], asyncio.Lock] = {}


def _host_drain_lock(room_id: str) -> asyncio.Lock:
    loop = asyncio.get_running_loop()
    key = (id(loop), room_id)
    lock = _host_drain_locks.get(key)
    if lock is None:
        lock = asyncio.Lock()
        _host_drain_locks[key] = lock
    return lock


def schedule_host_action_drain(room_id: str) -> None:
    """出队不得绑在提交者的 WebSocket 回调上；用当前事件循环后台任务执行。"""

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_drain_host_action_queue(room_id))


async def _queue_decision_for_submit(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
    client_action_id: str,
    state,
) -> str:
    """Return start | enqueue | reject for an action.plan.submit."""

    if state is None or state.status == "idle":
        return "start"
    if state.client_action_id == client_action_id:
        return "start"
    active = await action_plan_turn_application.active_for_room(room_id)
    if active is not None and active.parent_action_id == client_action_id:
        return "start"
    if active is not None and active.player_id == player_id:
        if active.status in _OWN_SUPERSEDE_STATUSES:
            return "start"
        if active.status in _OWN_WAITING_STATUSES:
            return "reject"
        return "enqueue"
    if state.player_id == player_id and state.status == "awaiting_player":
        return "reject"
    return "enqueue"


async def _enqueue_host_action(
    db: AsyncSession,
    websocket: WebSocket,
    *,
    room_id: str,
    player_id: str,
    actor_id: str,
    client_action_id: str,
    utterance: str,
    player_view: PlayerView,
    recipient: ActionRecipientPayload,
) -> None:
    try:
        item, created = await host_action_queue_service.enqueue(
            db,
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
            client_action_id=client_action_id,
            utterance=utterance,
            recipient=recipient,
        )
    except HostActionQueueError as exc:
        await _send_error(
            websocket,
            exc.code,
            exc.message,
            correlation_id=client_action_id,
        )
        return
    # NPC 原话必须等出队后二次验证和受众冻结完成再落 dialogue.player；
    # 不能先写 action.broadcast，否则会误入 Keeper Memory 和摘要。
    if created and recipient.kind == "keeper":
        await _broadcast_action_utterance(
            db,
            PlayerInput(
                room_id=room_id,
                player_id=player_id,
                actor_id=item.actor_id,
                client_action_id=item.client_action_id,
                utterance=item.utterance,
            ),
            player_view,
        )
    elif not created and recipient.kind == "npc" and item.status == "completed":
        correlations = (
            f"{client_action_id}:player",
            *(f"{client_action_id}:npc:{ordinal}" for ordinal in range(3)),
        )
        events = tuple(
            await db.scalars(
                select(Event)
                .where(
                    Event.room_id == room_id,
                    Event.correlation_id.in_(correlations),
                )
                .order_by(Event.created_at, Event.id)
            )
        )
        for event in events:
            audience = tuple(str(value) for value in event.payload.get("audiencePlayerIds", ()))
            await _broadcast_dialogue_event(db, event, audience)
    await _broadcast_room_action_state(db, room_id)


async def _npc_dialogue_audience(
    db: AsyncSession,
    *,
    room_id: str,
    scene_id: str,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """投影所有房间成员并冻结同场景玩家和 Actor；任一失败均整体重试。"""

    player_ids = tuple(await db.scalars(select(Player.id).where(Player.room_id == room_id)))
    audience_players: list[str] = []
    audience_actors: list[str] = []
    for player_id in player_ids:
        view = await session_view_application.current_player_view(
            room_id=room_id,
            player_id=player_id,
        )
        if view.scene.id == scene_id:
            audience_players.append(player_id)
            audience_actors.append(view.self_actor.id)
    return tuple(audience_players), tuple(audience_actors)


async def _broadcast_dialogue_event(
    db: AsyncSession,
    event: Event,
    audience_player_ids: tuple[str, ...],
) -> None:
    """提交成功后按冻结受众单播；离线玩家稍后通过 Event 回放恢复。"""

    envelope = await _dialogue_event_envelope(db, event)
    for target_player_id in audience_player_ids:
        await manager.send_to_player(event.room_id, target_player_id, envelope)


async def _dialogue_event_envelope(db: AsyncSession, event: Event) -> dict:
    """把 dialogue Event 还原成统一的 WS 信封，供广播和断线恢复复用。"""

    raw_payload = dict(event.payload)
    if event.event_type == "dialogue.player":
        payload = DialoguePlayerPayload.model_validate(raw_payload)
    else:
        avatar_url = await npc_dialogue_service.portrait_url(
            db,
            room_id=event.room_id,
            entity_id=str(raw_payload.get("speakerId", "")),
        )
        payload = DialogueNpcPayload.model_validate({**raw_payload, "avatarUrl": avatar_url})
    envelope = ServerEnvelope(
        type=event.event_type,
        payload=payload.model_dump(by_alias=True, mode="json"),
    ).model_dump(by_alias=True)
    return envelope


async def _recover_persisted_turn_followup_dialogue(
    db: AsyncSession,
    websocket: WebSocket,
    *,
    room_id: str,
    player_id: str,
    client_action_id: str,
    player_view: PlayerView,
    npc_replies: tuple[ActionPlanNpcReply, ...],
) -> None:
    """断线恢复时补发同回合追加的 NPC 回复，保持 narration 之后的展示顺序。"""

    if not npc_replies:
        return
    correlations = tuple(
        f"{client_action_id}:followup-npc:{ordinal}" for ordinal in range(len(npc_replies))
    )
    source_event = await room_service.get_correlated_event(
        db,
        room_id,
        "narration.push",
        client_action_id,
    )
    if source_event is None:
        raise RuntimeError("守秘人叙事已发送但 narration.push 未持久化")
    audience_player_ids, audience_actor_ids = await _npc_dialogue_audience(
        db,
        room_id=room_id,
        scene_id=player_view.scene.id,
    )
    visible_ids = {npc.id for npc in visible_dialogue_npcs(player_view)}
    existing_events = {
        event.correlation_id: event
        for event in await db.scalars(
            select(Event)
            .where(
                Event.room_id == room_id,
                Event.event_type == "dialogue.npc",
                Event.correlation_id.in_(correlations),
            )
            .order_by(Event.created_at.asc(), Event.id.asc())
        )
    }
    reply_events: list[Event | None] = [None] * len(npc_replies)
    for ordinal, reply in enumerate(npc_replies):
        if reply.speaker_id not in visible_ids:
            continue
        correlation = f"{client_action_id}:followup-npc:{ordinal}"
        existing = existing_events.get(correlation)
        if existing is not None:
            reply_events[ordinal] = existing
            continue
        persisted = await npc_dialogue_service.persist_scripted_replies(
            db,
            room_id=room_id,
            player_id=player_id,
            client_action_id=client_action_id,
            view=player_view,
            source_dialogue_id=source_event.id,
            audience_player_ids=audience_player_ids,
            audience_actor_ids=audience_actor_ids,
            npc_messages=((reply.speaker_id, reply.text),),
        )
        reply_events[ordinal] = persisted[0]
    for event in reply_events:
        if event is None:
            continue
        # 恢复时也按冻结受众广播；仅回复当前重连玩家会让同场景其他玩家永久漏掉
        # 这条已经补写的 NPC 台词。事件已按 correlation 幂等，重复恢复不会重复落库。
        await _broadcast_dialogue_event(db, event, audience_player_ids)


async def _emit_keeper_followup_dialogue(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
    client_action_id: str,
    player_view: PlayerView,
    narration,
) -> None:
    """守秘人叙事落库并广播后，再按顺序补发结构化 NPC 台词。"""

    if narration.kind != "narration" or not narration.npc_replies:
        return
    visible_ids = {npc.id for npc in visible_dialogue_npcs(player_view)}
    valid_replies = tuple(item for item in narration.npc_replies if item.speaker_id in visible_ids)
    if not valid_replies:
        return
    audience_player_ids, audience_actor_ids = await _npc_dialogue_audience(
        db,
        room_id=room_id,
        scene_id=player_view.scene.id,
    )
    source_event = await room_service.get_correlated_event(
        db,
        room_id,
        "narration.push",
        client_action_id,
    )
    if source_event is None:
        raise RuntimeError("守秘人叙事已发送但 narration.push 未持久化")
    reply_events = await npc_dialogue_service.persist_scripted_replies(
        db,
        room_id=room_id,
        player_id=player_id,
        client_action_id=client_action_id,
        view=player_view,
        source_dialogue_id=source_event.id,
        audience_player_ids=audience_player_ids,
        audience_actor_ids=audience_actor_ids,
        npc_messages=tuple((item.speaker_id, item.text) for item in valid_replies),
    )
    for event in reply_events:
        await _broadcast_dialogue_event(db, event, audience_player_ids)


async def _persist_npc_unavailable(
    db: AsyncSession,
    item,
    text: str,
) -> None:
    """NPC 出队时已失效，只向发起玩家保存并发送安全澄清。"""

    correlation = f"{item.client_action_id}:npc-unavailable"
    event = await room_service.get_correlated_event(
        db,
        item.room_id,
        "narration.push",
        correlation,
    )
    if event is None:
        event = Event(
            id=str(uuid.uuid4()),
            room_id=item.room_id,
            player_id=item.player_id,
            event_type="narration.push",
            correlation_id=correlation,
            visibility="player_scoped",
            actor_id=item.actor_id,
            payload=NarrationPushPayload(
                message_id=correlation,
                text=text,
            ).model_dump(by_alias=True),
            created_at=datetime.now(UTC),
        )
        db.add(event)
        await db.commit()
    envelope = ServerEnvelope(
        type="narration.push",
        payload=event.payload,
    ).model_dump(by_alias=True)
    await manager.send_to_player(item.room_id, item.player_id, envelope)


async def _run_queued_host_action(
    db: AsyncSession,
    item,
    view: PlayerView,
) -> None:
    """队列项统一走 Host 主链；NPC 只是在输入里多了一个结构化说话对象。"""

    claimed = await host_action_queue_service.claim_npc(
        db,
        item,
        lease_seconds=npc_dialogue_service.lease_seconds,
    )
    if claimed is None:
        return
    item = claimed
    try:
        require_dialogue_npc(view, item.recipient_entity_id or "")
        audience_player_ids, _ = await _npc_dialogue_audience(
            db,
            room_id=item.room_id,
            scene_id=view.scene.id,
        )
        if item.player_id not in audience_player_ids:
            raise RuntimeError("NPC 对话发起者不在冻结场景受众中")
        await db.refresh(item)
        if item.status == "cancelled":
            return
        if await db.get(Player, item.player_id) is None:
            raise ValueError("玩家已不在房间中")
        interlocutor_id = item.recipient_entity_id or None
        interlocutor_name = None
        if interlocutor_id is not None:
            interlocutor_name = require_dialogue_npc(view, interlocutor_id).name
        result = await action_plan_turn_application.start(
            room_id=item.room_id,
            player_id=item.player_id,
            client_action_id=item.client_action_id,
            utterance=item.utterance,
            interlocutor_id=interlocutor_id,
            interlocutor_name=interlocutor_name,
            on_progress=None,
            on_phase=None,
            on_input_accepted=partial(_broadcast_action_utterance, db),
        )
        await host_action_queue_service.mark_started(db, item)
        connections = manager.player_connections(item.room_id, item.player_id)
        websocket = connections[0] if connections else None
        await _send_action_plan_result(
            db,
            websocket,
            item.room_id,
            item.player_id,
            result,
        )
    except ValueError as exc:
        await host_action_queue_service.mark_npc_failed(db, item)
        for target_socket in manager.player_connections(item.room_id, item.player_id):
            await _send_turn_failed(target_socket, item.client_action_id, exc)
    except Exception as exc:
        if item.attempt_count < 2 and is_transient_model_error(exc):
            await host_action_queue_service.mark_npc_retryable(db, item)
            asyncio.get_running_loop().call_later(
                5,
                schedule_host_action_drain,
                item.room_id,
            )
            return
        await host_action_queue_service.mark_npc_failed(db, item)
        for target_socket in manager.player_connections(item.room_id, item.player_id):
            await _send_turn_failed(target_socket, item.client_action_id, exc)


async def _run_direct_host_action(
    db: AsyncSession,
    item,
    view: PlayerView,
    websocket: WebSocket | None,
    *,
    broadcast_state: bool = True,
) -> None:
    """Persist and deliver a frozen A1 response without entering ActionPlan."""

    await db.refresh(item)
    if item.status in _HOST_QUEUE_TERMINAL:
        return
    text = (item.direct_response_text or "").strip()
    if not text:
        raise RuntimeError("direct_response 队列项缺少已校验文本")
    kind = "clarification" if item.execution_provenance == "fallback_clarification" else "narration"
    existing = await room_service.get_correlated_event(
        db, item.room_id, "narration.push", item.client_action_id
    )
    recorded = existing is None
    if existing is None:
        payload = NarrationPushPayload(message_id=item.client_action_id, text=text).model_dump(
            by_alias=True
        )
        payload[room_service.PERSISTED_TURN_COMPLETION_KEY] = {
            "kind": kind,
            "claimed_fact_ids": [],
            "suggested_actions": [],
            "npc_reply_count": 0,
            "npc_replies": [],
        }
        try:
            existing = await room_service.record_event_pending(
                db,
                item.room_id,
                item.player_id,
                "narration.push",
                payload,
                visibility="public",
                actor_id=item.actor_id,
                scene_id=view.scene.id,
                view_revision=view.revision,
                correlation_id=item.client_action_id,
            )
        except IntegrityError:
            await db.rollback()
            existing = await room_service.get_correlated_event(
                db, item.room_id, "narration.push", item.client_action_id
            )
            if existing is None:
                raise
            recorded = False
    item.result_event_ids = [existing.id]
    item.status = "completed"
    item.lease_owner = None
    item.lease_expires_at = None
    item.next_attempt_at = None
    item.updated_at = datetime.now(UTC)
    await db.commit()

    narration = NarrationOutput(kind=kind, text=normalize_narration_text(text))
    await _send_to_player(
        websocket,
        {
            "protocol_version": "1",
            "message_type": "turn.completed",
            "correlation_id": item.client_action_id,
            "payload": {
                "room_id": item.room_id,
                "player_id": item.player_id,
                "actor_id": item.actor_id,
                "narration": narration.model_dump(mode="json"),
                "player_view": view.to_json_dict(),
            },
        },
    )
    await _send_view_updated(websocket, item.player_id, view)
    if recorded:
        await _emit_turn_narration(
            websocket,
            item.room_id,
            client_action_id=item.client_action_id,
            narration=narration,
        )
    elif websocket is not None:
        await _send_to_player(
            websocket,
            ServerEnvelope(
                type="narration.push",
                payload=NarrationPushPayload(
                    message_id=item.client_action_id, text=text
                ).model_dump(by_alias=True),
            ).model_dump(by_alias=True),
        )
    if broadcast_state:
        await _broadcast_room_action_state_fresh(item.room_id)


async def _recover_keeper_queue_failure(
    db: AsyncSession,
    item,
    websocket: WebSocket | None,
    exc: Exception,
    *,
    room_id: str,
) -> None:
    """Keep frozen keeper work retryable; only fail closed after the last attempt.

    Discarding a processing item made the same client_action_id unrecoverable and
    could drop a route that had already been frozen.  Delivery errors after the
    event+queue commit must leave the item completed so reconnect can replay.
    """

    client_action_id = item.client_action_id
    try:
        await db.rollback()
    except SQLAlchemyError:
        logger.warning(
            "host_queue_rollback_after_failure",
            room_id=room_id,
            client_action_id=client_action_id,
            error_type=type(exc).__name__,
            error_reason=_turn_error_reason(exc),
        )
    persisted = await host_action_queue_service.get_by_client_action(db, room_id, client_action_id)
    if persisted is not None:
        item = persisted
    route = host_action_queue_service.effective_execution_route(item)
    if (
        item.recipient_kind == "keeper"
        and route == "direct_response"
        and item.status == "completed"
    ):
        logger.warning(
            "host_direct_response_delivery_failed_after_commit",
            room_id=room_id,
            client_action_id=client_action_id,
            error_type=type(exc).__name__,
            error_reason=_turn_error_reason(exc),
        )
        return
    if item.recipient_kind == "keeper" and item.status == "processing":
        if item.attempt_count < 2:
            await host_action_queue_service.mark_npc_retryable(db, item, delay_seconds=0)
            return
        await host_action_queue_service.mark_npc_failed(db, item)
        log_turn_failed(
            room_id=room_id,
            stage="队列出队",
            code=_map_turn_error(exc)[0],
            correlation_id=client_action_id,
            error_type=type(exc).__name__,
            error_reason=_turn_error_reason(exc),
            exc=exc,
        )
        await _send_turn_failed(websocket, client_action_id, exc)
        return
    await host_action_queue_service.discard(db, item)
    log_turn_failed(
        room_id=room_id,
        stage="队列出队",
        code=_map_turn_error(exc)[0],
        correlation_id=client_action_id,
        error_type=type(exc).__name__,
        error_reason=_turn_error_reason(exc),
        exc=exc,
    )
    await _send_turn_failed(websocket, client_action_id, exc)


async def _drain_host_action_queue(room_id: str) -> None:
    async with _host_drain_lock(room_id):
        while True:
            async with _short_db_session() as db:
                state = await _current_room_action_state(db, room_id)
                if state is None or state.status != "idle":
                    return
                item = await host_action_queue_service.peek_next(db, room_id)
                if item is None:
                    return
                try:
                    view = await session_view_application.current_player_view(
                        room_id=room_id,
                        player_id=item.player_id,
                    )
                except Exception as exc:
                    # 只有身份已经失效才丢弃。投影层的瞬时失败（库锁、运行时
                    # 还在恢复）必须把已接受的队列项留着，等下一次出队再试。
                    if not _is_stale_queued_actor_error(exc):
                        logger.warning(
                            "host_queue_projection_deferred",
                            room_id=room_id,
                            client_action_id=item.client_action_id,
                            error_type=type(exc).__name__,
                            error_reason=_turn_error_reason(exc),
                        )
                        return
                    await host_action_queue_service.discard(db, item)
                    continue
                if view.self_actor.id != item.actor_id:
                    await host_action_queue_service.discard(db, item)
                    continue
                if item.recipient_kind == "npc":
                    try:
                        require_dialogue_npc(view, item.recipient_entity_id or "")
                    except ValueError:
                        await _persist_npc_unavailable(
                            db,
                            item,
                            "你想交谈的 NPC 已不在当前场景，或现在无法回应。",
                        )
                        await host_action_queue_service.discard(db, item)
                        continue
                lock_token = action_lock_manager.try_acquire(
                    room_id,
                    player_id=item.player_id,
                    actor_id=item.actor_id,
                    client_action_id=item.client_action_id,
                    revision=view.revision,
                )
                if lock_token is None:
                    return
                connections = manager.player_connections(room_id, item.player_id)
                websocket = connections[0] if connections else None
                try:
                    await _send_turn_event(
                        websocket,
                        TurnStarted(correlation_id=item.client_action_id),
                    )
                    await _broadcast_room_action_state(db, room_id)
                    if item.recipient_kind == "npc":
                        await _run_queued_host_action(db, item, view)
                        continue
                    # Keeper items use the durable lease shared with NPC items.  A
                    # decision is frozen before either route executes, so a retry or
                    # process restart cannot call the router twice.
                    claimed = await host_action_queue_service.claim(
                        db,
                        item,
                        recipient_kind="keeper",
                        lease_seconds=180,
                    )
                    if claimed is None:
                        return
                    item = claimed
                    route = host_action_queue_service.effective_execution_route(item)
                    if route == "unresolved":
                        history = await _public_host_history(
                            db,
                            room_id,
                            exclude_correlation_id=item.client_action_id,
                        )
                        context = HostPublicContextProjector(
                            max_turns=get_settings().recent_history_max_turns,
                            max_chars=get_settings().recent_history_max_chars,
                        ).project(
                            view,
                            current_keeper_text=item.utterance,
                            public_history=history,
                        )
                        decision, provenance = await _get_host_entry_router().decide(context)
                        await host_action_queue_service.save_execution_route(
                            db,
                            item,
                            route=decision.route,
                            text=decision.text,
                            provenance=provenance,
                        )
                        route = decision.route
                        await db.refresh(item)
                    if route == "direct_response":
                        await _run_direct_host_action(db, item, view, websocket)
                        continue
                    # delegate_to_legacy intentionally enters the unchanged
                    # ActionPlan application below.
                    interlocutor_id = None
                    interlocutor_name = None
                    result = await action_plan_turn_application.start(
                        room_id=room_id,
                        player_id=item.player_id,
                        client_action_id=item.client_action_id,
                        utterance=item.utterance,
                        interlocutor_id=interlocutor_id,
                        interlocutor_name=interlocutor_name,
                        on_progress=lambda event, target=websocket: _send_plan_progress(
                            target,
                            event,
                        ),
                        on_phase=partial(
                            _send_turn_phase,
                            websocket,
                            item.client_action_id,
                        ),
                        on_input_accepted=None,
                    )
                    await host_action_queue_service.mark_started(db, item)
                    await _send_action_plan_result(
                        db,
                        websocket,
                        room_id,
                        item.player_id,
                        result,
                    )
                    if result.waiting_for_player:
                        return
                except Exception as exc:
                    await _recover_keeper_queue_failure(
                        db,
                        item,
                        websocket,
                        exc,
                        room_id=room_id,
                    )
                finally:
                    with anyio.CancelScope(shield=True):
                        action_lock_manager.release(room_id, lock_token)
                        await _broadcast_room_action_state_fresh(room_id)


async def _broadcast_player_views(room_id: str) -> None:
    """分别投影并单播每名在线玩家的视图，绝不复用发起者的私有视图。"""

    for player_id in manager.player_ids(room_id):
        try:
            view = await session_view_application.current_player_view(
                room_id=room_id,
                player_id=player_id,
            )
        except Exception:
            logger.exception(
                "multiplayer_view_projection_failed",
                room_id=room_id,
                player_id=player_id,
            )
            continue
        payload = ViewUpdatedPayload(player_id=player_id, player_view=view)
        envelope = ServerEnvelope(
            type="view.updated",
            payload=payload.model_dump(by_alias=True, mode="json"),
        )
        await manager.send_to_player(
            room_id,
            player_id,
            envelope.model_dump(by_alias=True),
        )


class _PersistedTurnCompletion(BaseModel):
    """Backend-only metadata needed to replay a completed turn exactly."""

    kind: Literal["narration", "clarification"] = "narration"
    claimed_fact_ids: tuple[str, ...] = ()
    suggested_actions: tuple[str, ...] = Field(default=(), max_length=3)
    # 既记录条数也记录原始回复文本，恢复时如果 follow-up 还没写进 dialogue.npc，
    # 这里就能直接补写，不会把 NPC 回答永久丢在恢复竞态里。
    npc_reply_count: int = Field(default=0, ge=0, le=3)
    npc_replies: tuple[ActionPlanNpcReply, ...] = Field(default=(), max_length=3)


@asynccontextmanager
async def _short_db_session() -> AsyncIterator[AsyncSession]:
    """Always finish SQLAlchemy cleanup even when a WebSocket task is cancelled."""

    session = async_session_factory()
    try:
        yield session
    finally:
        with anyio.CancelScope(shield=True):
            await session.close()


def _connection_is_gone(websocket: WebSocket, exc: Exception) -> bool:
    """这个连接是不是已经联系不上了。

    对端断开有两种表现：Starlette 自己发现状态不对，抛
    `Cannot call "send" once a close message has been sent.`（此时
    application_state 必然已是 DISCONNECTED，见 starlette/websockets.py 的
    send()）；以及底层 TCP 已断但 application_state 还没被标记，直接从 uvloop
    抛出 `unable to perform operation on <TCPTransport closed=True ...>`。
    OSError 会被 Starlette 转成 WebSocketDisconnect。

    只认这三种。别的异常（比如 payload 不可序列化）是真的出了问题，必须继续
    往上抛，不能被"对端可能断了"顺手吞掉。
    """

    if isinstance(exc, WebSocketDisconnect):
        return True
    return isinstance(exc, RuntimeError) and (
        websocket.application_state is WebSocketState.DISCONNECTED or "closed" in str(exc).lower()
    )


async def _send_to_player(websocket: WebSocket | None, message: dict) -> bool:
    """单播一帧；对端已经断了就丢掉这一帧，不打断正在跑的回合。

    回合是在收消息循环里内联跑完的，进度、阶段和结算帧都直接写这个 socket。
    玩家中途掉线/刷新时，这些 send 会抛异常并把回合从中间掐断——规则效果已经
    事务提交，叙事却还没落库（`_deliver_turn_narration` 在发送链的末尾），世界
    推进了但解释它的那段话永远消失。房间广播早就是容断的（见
    service/ws_manager.py 的 broadcast），单播这条通道之前不是。

    返回是否真的送达，让调用方能记日志；但**不构成控制流**：一个已经断开的
    连接不该影响这一回合能不能跑完、能不能落库。
    """

    if websocket is None:
        return False
    try:
        await websocket.send_json(message)
    except Exception as exc:
        if not _connection_is_gone(websocket, exc):
            raise
        logger.info(
            "ws_send_dropped",
            message_type=message.get("type") or message.get("message_type"),
            correlation_id=message.get("correlation_id"),
        )
        return False
    return True


async def _send_error(
    websocket: WebSocket,
    code: str,
    message: str,
    *,
    correlation_id: str | None = None,
) -> None:
    """只发给触发这次交互的那一个连接，不广播——`error` 事件是"告诉发起者
    这次请求怎么了"，不是房间广播内容（issue #77 新增）。"""
    payload = ErrorPayload(code=code, message=message, correlation_id=correlation_id)
    envelope = ServerEnvelope(type="error", payload=payload.model_dump(by_alias=True))
    await _send_to_player(websocket, envelope.model_dump(by_alias=True))


async def _broadcast_time_advance(
    room_id: str,
    payload: TimeAdvancePendingPayload | TimeAdvanceResolvedPayload,
) -> None:
    """广播完整提案快照，让各客户端用同一权威状态覆盖本地 UI。"""

    event_type = (
        "time.advance.pending"
        if isinstance(payload, TimeAdvancePendingPayload)
        else "time.advance.resolved"
    )
    envelope = ServerEnvelope(
        type=event_type,
        payload=payload.model_dump(by_alias=True, mode="json"),
    )
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))


async def _broadcast_scene_transition(
    room_id: str,
    payload: SceneTransitionPendingPayload | SceneTransitionResolvedPayload,
) -> None:
    event_type = (
        "scene.transition.pending"
        if isinstance(payload, SceneTransitionPendingPayload)
        else "scene.transition.resolved"
    )
    envelope = ServerEnvelope(
        type=event_type,
        payload=payload.model_dump(by_alias=True, mode="json"),
    )
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))


async def _send_turn_event(
    websocket: WebSocket | None,
    event: TurnEvent,
) -> None:
    payload: (
        TurnStartedPayload
        | TurnPhaseChangedPayload
        | ToolStartedPayload
        | ToolCompletedPayload
        | TurnFailedPayload
    )
    if isinstance(event, TurnStarted):
        payload = TurnStartedPayload(correlation_id=event.correlation_id)
    elif isinstance(event, TurnPhaseChanged):
        payload = TurnPhaseChangedPayload(
            correlation_id=event.correlation_id,
            phase=event.phase,
        )
    elif isinstance(event, TurnToolStarted):
        payload = ToolStartedPayload(
            correlation_id=event.correlation_id,
            tool_name=event.tool_name,
            public_progress_label=event.public_progress_label,
        )
    elif isinstance(event, TurnToolCompleted):
        payload = ToolCompletedPayload(
            correlation_id=event.correlation_id,
            tool_name=event.tool_name,
            status=event.status,
        )
    else:
        payload = TurnFailedPayload(
            correlation_id=event.correlation_id,
            code=event.code,
            public_message=event.public_message,
            retryable=event.retryable,
        )
    envelope = ServerEnvelope(
        type=event.type,
        payload=payload.model_dump(by_alias=True),
    )
    await _send_to_player(websocket, envelope.model_dump(by_alias=True))


async def _send_turn_failed(
    websocket: WebSocket | None,
    correlation_id: str,
    exc: Exception,
) -> None:
    code, public_message, retryable = _map_turn_error(exc)
    await _send_turn_event(
        websocket,
        TurnFailed(
            correlation_id=correlation_id,
            code=code,
            public_message=public_message,
            retryable=retryable,
        ),
    )


async def _send_turn_phase(
    websocket: WebSocket | None,
    correlation_id: str,
    phase: TurnPhase,
) -> None:
    await _send_turn_event(
        websocket,
        TurnPhaseChanged(correlation_id=correlation_id, phase=phase),
    )


async def _send_plan_progress(websocket: WebSocket | None, event) -> None:
    # One-step runs are internal normalization and do not expose a useless
    # 1/1 progress timeline. Keep this gate here so reconnect replay and live
    # observer events share exactly the same behavior.
    if event.total_steps == 1 and event.type in {
        "plan.started",
        "plan.step_changed",
        "plan.completed",
    }:
        return
    payload = PlanProgressPayload(
        correlation_id=event.correlation_id,
        current_step=event.current_step,
        completed_steps=event.completed_steps,
        total_steps=event.total_steps,
        phase=event.phase,
        public_progress_label=event.public_progress_label,
        safe_reason=event.safe_reason,
    )
    await _send_to_player(
        websocket,
        ServerEnvelope(
            type=event.type,
            payload=payload.model_dump(by_alias=True),
        ).model_dump(by_alias=True),
    )


async def _resume_after_authoritative_decision(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
    parent_action_id: str,
    on_progress=None,
    on_phase=None,
) -> ActionPlanTurnResult:
    """Resume a Run, or render a verified pre-cutover Engine action."""
    if await action_plan_turn_application.get_plan(room_id, parent_action_id) is not None:
        return await action_plan_turn_application.resume_pending(
            room_id=room_id,
            player_id=player_id,
            parent_action_id=parent_action_id,
            on_progress=on_progress,
            on_phase=on_phase,
        )
    recovery = await legacy_single_action_recovery.recover(
        GetAdjudicationStatusRequest(
            room_id=room_id,
            player_id=player_id,
            action_request_id=parent_action_id,
        )
    )
    if recovery is None:
        raise TurnExecutionError(
            "PLAN_RUN_MISSING",
            "行动运行记录缺失，无法安全恢复",
            retryable=False,
        )
    return await action_plan_turn_application.finish_legacy_recovery(
        recovery,
        room_id=room_id,
        player_id=player_id,
        on_phase=on_phase,
    )


def _check_decision_engine() -> ConsentAwareAdjudicationEngine:
    """检定结算必须经过确认装饰器，才能在成功的换场景效果上开全员确认。"""

    engine = adjudication_engine_service
    if isinstance(engine, ConsentAwareAdjudicationEngine):
        return engine
    return ConsentAwareAdjudicationEngine(engine, async_session_factory)


def _require_pending_adjudication_status(
    status: str,
) -> Literal["awaiting_skill_choice", "awaiting_post_roll_decision"]:
    """Narrow an execution status before exposing a pending-decision payload."""

    if status == "awaiting_skill_choice":
        return "awaiting_skill_choice"
    if status == "awaiting_post_roll_decision":
        return "awaiting_post_roll_decision"
    raise ContractError("等待玩家的行动缺少 pending adjudication 状态")


async def _send_action_plan_result(
    db: AsyncSession,
    websocket: WebSocket | None,
    room_id: str,
    player_id: str,
    result: ActionPlanTurnResult,
    before_completed: Callable[[], Awaitable[None]] | None = None,
) -> bool:
    if result.waiting_for_player:
        execution = result.execution
        if execution is None:
            raise ContractError("waiting_for_player 缺少 adjudication execution")
        if execution.status == "awaiting_time_consent":
            if execution.time_advance_proposal_id is None:
                raise ContractError("待确认行动缺少时间提案 ID")
            await time_advance_service.bind_parent_action(
                db,
                room_id=room_id,
                proposal_id=execution.time_advance_proposal_id,
                player_id=player_id,
                parent_action_id=result.player_input.client_action_id,
            )
            pending_time = await time_advance_service.get_pending(
                db,
                room_id,
                engine=adjudication_engine_service,
            )
            if not isinstance(pending_time, TimeAdvancePendingPayload):
                raise ContractError("待确认行动缺少持久化时间提案")
            # 先发布等待态，再发布具体提案，前端收到按钮时不会短暂保留 processing。
            await _broadcast_room_action_state(db, room_id)
            await _broadcast_time_advance(room_id, pending_time)
            return False
        if execution.status == "awaiting_scene_consent":
            if execution.scene_transition_proposal_id is None:
                raise ContractError("待确认行动缺少场景提案 ID")
            await scene_transition_service.bind_parent_action(
                db,
                room_id=room_id,
                proposal_id=execution.scene_transition_proposal_id,
                player_id=player_id,
                parent_action_id=result.player_input.client_action_id,
            )
            pending_scene = await scene_transition_service.get_pending(
                db,
                room_id,
                engine=adjudication_engine_service,
            )
            if not isinstance(pending_scene, SceneTransitionPendingPayload):
                raise ContractError("待确认行动缺少持久化场景提案")
            await _broadcast_room_action_state(db, room_id)
            await _broadcast_scene_transition(room_id, pending_scene)
            return False
        pending = AdjudicationPendingPayload(
            correlation_id=result.player_input.client_action_id,
            plan_id=result.plan_id,
            source_revision=execution.view_revision,
            status=_require_pending_adjudication_status(execution.status),
            pending_decision=execution.pending_decision,
            check_run=execution.check_run,
        )
        await _send_to_player(
            websocket,
            ServerEnvelope(
                type="adjudication.pending",
                payload=pending.model_dump(by_alias=True, mode="json"),
            ).model_dump(by_alias=True),
        )
        await _broadcast_player_views(room_id)
        await _broadcast_room_action_state(db, room_id)
        return False

    narration = result.narration
    if narration is None:
        raise ContractError("settled ActionPlan 缺少 narration")
    output = NarrationOutput(
        kind=narration.kind,
        text=narration.text,
        claimed_fact_ids=narration.claimed_evidence_refs,
        suggested_actions=narration.suggested_actions,
    )
    # 权威状态已经提交，先为每名在线玩家独立投影；最终叙事发出后客户端可立即断开，
    # 因此不能把这项数据库工作留在叙事之后。
    await _broadcast_player_views(room_id)

    deferred_progress: list[object] = []

    async def _defer_plan_progress(event: object) -> None:
        deferred_progress.append(event)

    async def _finalize_before_completed() -> None:
        # The narration event is already durable when this callback runs. Finish the
        # Run before publishing turn.completed so an immediate next action cannot
        # observe the previous Run as active.
        with anyio.CancelScope(shield=True):
            await time_advance_service.mark_narration_persisted(
                db,
                room_id=room_id,
                parent_action_id=result.player_input.client_action_id,
            )
            await scene_transition_service.mark_narration_persisted(
                db,
                room_id=room_id,
                parent_action_id=result.player_input.client_action_id,
            )
            await action_plan_turn_application.mark_narration_persisted(
                room_id=room_id,
                parent_action_id=result.player_input.client_action_id,
                on_progress=_defer_plan_progress,
            )
            if before_completed is not None:
                await before_completed()

    async def _flush_deferred_progress() -> None:
        for event in deferred_progress:
            await _send_plan_progress(websocket, event)

    async def _after_turn_narration() -> None:
        await _flush_deferred_progress()
        try:
            # Keeper 权威结果先提交；后续 NPC 台词只是追加展示，失败时绝不能把本回合
            # 回滚成 turn.failed，更不能影响已经提交的 PlayerView。
            await _emit_keeper_followup_dialogue(
                db,
                room_id=room_id,
                player_id=player_id,
                client_action_id=result.player_input.client_action_id,
                player_view=result.player_view,
                narration=narration,
            )
        except Exception:
            logger.warning(
                "keeper_followup_dialogue_failed",
                room_id=room_id,
                player_id=player_id,
                action_id=result.player_input.client_action_id,
                exc_info=True,
            )

    recorded = await _send_completed_turn_message(
        db,
        websocket,
        room_id,
        player_id,
        actor_id=result.player_input.actor_id,
        client_action_id=result.player_input.client_action_id,
        player_view=result.player_view,
        narration=output,
        npc_reply_count=len(narration.npc_replies),
        npc_replies=narration.npc_replies,
        before_completed=_finalize_before_completed,
        after_narration=_after_turn_narration,
    )
    with anyio.CancelScope(shield=True):
        await _broadcast_room_action_state(db, room_id)
    schedule_host_action_drain(room_id)
    return recorded


async def _send_completed_turn_message(
    db: AsyncSession,
    websocket: WebSocket | None,
    room_id: str,
    player_id: str,
    *,
    actor_id: str,
    client_action_id: str,
    player_view: PlayerView,
    narration: NarrationOutput,
    npc_reply_count: int = 0,
    npc_replies: tuple[ActionPlanNpcReply, ...] = (),
    before_completed: Callable[[], Awaitable[None]] | None = None,
    after_narration: Callable[[], Awaitable[None]] | None = None,
) -> bool:
    """Make completion durable, then preserve the established socket event order."""

    recorded, persisted_narration = await _persist_turn_narration(
        db,
        room_id,
        player_id,
        client_action_id=client_action_id,
        narration=narration,
        npc_replies=npc_replies,
        actor_id=actor_id,
        scene_id=player_view.scene_id,
        view_revision=player_view.revision,
        npc_reply_count=npc_reply_count,
    )
    if before_completed is not None:
        await before_completed()
    await _send_to_player(
        websocket,
        {
            "protocol_version": "1",
            "message_type": "turn.completed",
            "correlation_id": client_action_id,
            "payload": {
                "room_id": room_id,
                "player_id": player_id,
                "actor_id": actor_id,
                "narration": narration.model_dump(mode="json"),
                "player_view": player_view.to_json_dict(),
            },
        },
    )
    await _send_view_updated(websocket, player_id, player_view)
    if recorded:
        await _emit_turn_narration(
            websocket,
            room_id,
            client_action_id=client_action_id,
            narration=persisted_narration,
        )
    # 摘要是异步可重建读模型，不能阻塞本回合的权威叙事发送。
    # 队列出队时 websocket 可能是 None，回退到应用单例上的同一服务。
    summary_service = None
    if websocket is not None:
        summary_service = getattr(websocket.app.state, "conversation_summary_service", None)
    if summary_service is None:
        from app.main import app as fastapi_app

        summary_service = getattr(fastapi_app.state, "conversation_summary_service", None)
    if summary_service is not None:
        # 摘要是异步读模型；公开事件为所有玩家入队，但不能阻塞回合响应。
        asyncio.create_task(
            summary_service.enqueue_room_if_needed(room_id=room_id),
            name=f"enqueue-conversation-summary-{room_id}",
        )
    if after_narration is not None:
        await after_narration()
    return recorded


async def _recover_persisted_turn_narration(
    db: AsyncSession,
    websocket: WebSocket | None,
    *,
    room_id: str,
    player_id: str,
    client_action_id: str,
) -> bool:
    # A1 direct responses have no ActionPlan/Engine record.  Recover from the
    # queue item's frozen text and correlated public event instead.
    queued_item = await host_action_queue_service.get_by_client_action(
        db, room_id, client_action_id
    )
    if (
        queued_item is not None
        and host_action_queue_service.effective_execution_route(queued_item) == "direct_response"
    ):
        if queued_item.player_id != player_id:
            raise ContractError("持久化 direct response 不属于当前玩家")
        if queued_item.status in _HOST_QUEUE_TERMINAL:
            await _send_turn_failed(
                websocket,
                client_action_id,
                TurnExecutionError(
                    "TURN_INTERNAL_ERROR",
                    "本次动作处理失败，请稍后重试",
                    retryable=False,
                ),
            )
            return True
        view = await session_view_application.current_player_view(
            room_id=room_id,
            player_id=player_id,
        )
        if queued_item.status != "processing":
            claimed = await host_action_queue_service.claim(
                db, queued_item, recipient_kind="keeper", lease_seconds=180
            )
            if claimed is not None:
                queued_item = claimed
        await _run_direct_host_action(
            db,
            queued_item,
            view,
            websocket,
            broadcast_state=queued_item.status != "completed",
        )
        return True
    active = await action_plan_turn_application.get_plan(room_id, client_action_id)
    existing = await room_service.get_correlated_event(
        db,
        room_id,
        "narration.push",
        client_action_id,
    )
    if existing is None:
        return False

    actor_id: str | None = None
    if active is not None:
        if (
            active.parent_action_id != client_action_id
            or active.player_id != player_id
            or active.status not in {"awaiting_narration", "completed"}
        ):
            return False
        actor_id = active.actor_id
    else:
        recovery = await legacy_single_action_recovery.recover(
            GetAdjudicationStatusRequest(
                room_id=room_id,
                player_id=player_id,
                action_request_id=client_action_id,
            )
        )
        if recovery is None or recovery.execution.status not in TERMINAL_ADJUDICATION_STATUSES:
            return False
        actor_id = recovery.actor_id

    if existing.player_id not in {None, player_id}:
        raise ContractError("持久化 narration 不属于当前玩家")
    if existing.actor_id not in {None, actor_id}:
        raise ContractError("持久化 narration 不属于当前 Actor")
    persisted = NarrationPushPayload.model_validate(existing.payload)
    raw_completion = existing.payload.get(room_service.PERSISTED_TURN_COMPLETION_KEY)
    if raw_completion is None:
        narration = NarrationOutput(
            kind="clarification" if existing.visibility == "player_scoped" else "narration",
            text=normalize_narration_text(persisted.text),
        )
    else:
        try:
            completion = _PersistedTurnCompletion.model_validate(raw_completion)
        except ValidationError as exc:
            raise ContractError("持久化 narration 完成快照损坏") from exc
        narration = NarrationOutput(
            kind=completion.kind,
            text=normalize_narration_text(persisted.text),
            claimed_fact_ids=completion.claimed_fact_ids,
            suggested_actions=completion.suggested_actions,
        )
    view = await session_view_application.current_player_view(
        room_id=room_id,
        player_id=player_id,
    )
    await _send_to_player(
        websocket,
        {
            "protocol_version": "1",
            "message_type": "turn.completed",
            "correlation_id": client_action_id,
            "payload": {
                "room_id": room_id,
                "player_id": player_id,
                "actor_id": actor_id,
                "narration": narration.model_dump(mode="json"),
                "player_view": view.to_json_dict(),
            },
        },
    )
    await _send_to_player(
        websocket,
        ServerEnvelope(
            type="narration.push",
            payload=persisted.model_dump(by_alias=True),
        ).model_dump(by_alias=True),
    )
    if websocket is not None and raw_completion is not None and completion.npc_replies:
        await _recover_persisted_turn_followup_dialogue(
            db,
            websocket,
            room_id=room_id,
            player_id=player_id,
            client_action_id=client_action_id,
            player_view=view,
            npc_replies=completion.npc_replies,
        )
    await _send_view_updated(websocket, player_id, view)
    if active is not None:
        await action_plan_turn_application.mark_narration_persisted(
            room_id=room_id,
            parent_action_id=client_action_id,
            on_progress=lambda event: _send_plan_progress(websocket, event),
        )
    return True


async def _send_view_updated(
    websocket: WebSocket | None,
    player_id: str,
    player_view: PlayerView,
) -> None:
    payload = ViewUpdatedPayload(
        player_id=player_id,
        player_view=player_view,
    )
    envelope = ServerEnvelope(
        type="view.updated",
        payload=payload.model_dump(by_alias=True),
    )
    await _send_to_player(websocket, envelope.model_dump(by_alias=True))


async def _stream_narration_chunks(
    # 广播返回 None，单播返回"是否送达"，两者都只当投递用，返回值不参与切片逻辑。
    send: Callable[[dict], Awaitable[object]],
    *,
    message_id: str,
    text: str,
) -> None:
    """把一条已校验、已落库的叙事按句切片，作为渐进展示先行下发（issue #203）。

    调用前提有两条，缺一条都不能调：完整叙事已经过 `Narrator` 的 Schema 与
    事实引用校验；并且 `record_event()` 去重成功。片段本身**没有**独立的安全
    保证，也不落库——它只是同一条 `narration.push` 的展示形式，历史恢复、
    复盘和语音朗读一律只认随后发出的权威 `narration.push`。

    只切出一段时直接返回：单片段没有渐进可言，再发一轮 chunk 只是白白多一次
    往返，前端收到最终 `narration.push` 的时机完全一样。
    """

    chunks = split_narration_chunks(text)
    if len(chunks) < 2:
        return
    for sequence, chunk in enumerate(chunks):
        payload = NarrationChunkPayload(
            message_id=message_id,
            sequence=sequence,
            text=chunk,
        )
        envelope = ServerEnvelope(
            type="narration.chunk",
            payload=payload.model_dump(by_alias=True),
        )
        await send(envelope.model_dump(by_alias=True))


async def _send_persisted_opening(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
) -> bool:
    """Replay the authoritative opening to one authenticated room connection.

    This direct replay closes the hand-off race between the frontend's one-shot
    conversation request and WebSocket registration: a socket registered before
    the opening commit receives the later broadcast, while a socket registered
    after the commit receives this persisted copy. Delivery may overlap at the
    boundary, so clients still deduplicate by the stable ``game-opening`` ID.
    """

    existing = await room_service.get_correlated_event(
        db,
        room_id,
        "narration.push",
        _OPENING_MESSAGE_ID,
    )
    if existing is None:
        return False
    persisted = NarrationPushPayload.model_validate(existing.payload)
    narration = persisted.model_copy(
        update={
            "message_id": _OPENING_MESSAGE_ID,
            "text": normalize_narration_text(persisted.text),
        }
    )
    envelope = ServerEnvelope(
        type="narration.push",
        payload=narration.model_dump(by_alias=True),
    )
    await _send_to_player(websocket, envelope.model_dump(by_alias=True))
    return True


async def _ensure_opening_narration(
    db: AsyncSession,
    room_id: str,
    player_view: PlayerView,
) -> bool:
    """Persist and broadcast the room's single authoritative opening."""

    existing = await room_service.get_correlated_event(
        db,
        room_id,
        "narration.push",
        _OPENING_MESSAGE_ID,
    )
    if existing is not None:
        return False

    if session_view_application.opening_narration_mode == "model":
        started = OpeningStartedPayload(message_id=_OPENING_MESSAGE_ID)
        await manager.broadcast(
            room_id,
            ServerEnvelope(
                type="opening.started",
                payload=started.model_dump(by_alias=True),
            ).model_dump(by_alias=True),
        )

    generated = await session_view_application.generate_opening(player_view)
    narration = NarrationPushPayload(
        message_id=_OPENING_MESSAGE_ID,
        text=normalize_narration_text(generated.narration.text),
    )
    payload = narration.model_dump(by_alias=True)
    recorded = await room_service.record_event(
        db,
        room_id,
        None,
        "narration.push",
        payload,
        visibility="public",
        actor_id=None,
        scene_id=player_view.scene_id,
        view_revision=player_view.revision,
        correlation_id=_OPENING_MESSAGE_ID,
    )
    if not recorded:
        await room_service.get_correlated_event(
            db,
            room_id,
            "narration.push",
            _OPENING_MESSAGE_ID,
        )
        return False
    await _stream_narration_chunks(
        partial(manager.broadcast, room_id),
        message_id=_OPENING_MESSAGE_ID,
        text=narration.text,
    )
    envelope = ServerEnvelope(type="narration.push", payload=payload)
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))
    return True


async def _persist_turn_narration(
    db: AsyncSession,
    room_id: str,
    player_id: str,
    *,
    client_action_id: str,
    narration: NarrationOutput,
    actor_id: str,
    scene_id: str,
    view_revision: str,
    npc_reply_count: int = 0,
    npc_replies: tuple[ActionPlanNpcReply, ...] = (),
) -> tuple[bool, NarrationOutput]:
    """Persist one authoritative narration before its completion is announced."""

    text = normalize_narration_text(narration.text)
    completion = narration.model_copy(update={"text": text})
    push = NarrationPushPayload(
        message_id=client_action_id,
        text=text,
    )
    payload = push.model_dump(by_alias=True)
    payload[room_service.PERSISTED_TURN_COMPLETION_KEY] = {
        "kind": completion.kind,
        "claimed_fact_ids": list(completion.claimed_fact_ids),
        "suggested_actions": list(completion.suggested_actions),
        "npc_reply_count": npc_reply_count,
        "npc_replies": [reply.model_dump(mode="json") for reply in npc_replies],
    }
    recorded = await room_service.record_event(
        db,
        room_id,
        player_id,
        "narration.push",
        payload,
        # 澄清问话也是桌面上的主持人发言，同房其他玩家必须能看到、刷新后也能
        # 从 conversation 拉回来。真正的私密信息不走 narration.push（#48/#68）。
        visibility="public",
        actor_id=actor_id,
        scene_id=scene_id,
        view_revision=view_revision,
        correlation_id=client_action_id,
    )
    if not recorded:
        return False, completion
    log_narration_output(
        room_id=room_id,
        correlation_id=client_action_id,
        text=text,
        clarification=completion.kind == "clarification",
    )
    return True, completion


async def _emit_turn_narration(
    _websocket: WebSocket | None,
    room_id: str,
    *,
    client_action_id: str,
    narration: NarrationOutput,
) -> None:
    """Emit a narration that has already passed validation and persistence.

    `_websocket` 是历史参数：澄清曾经按发起者单播，队列出队时用该连接。
    `narration.push` 现已一律房间广播，同桌其他人必须能听到主持人问话。
    """

    push = NarrationPushPayload(
        message_id=client_action_id,
        text=narration.text,
    )
    send = partial(manager.broadcast, room_id)
    await _stream_narration_chunks(
        send,
        message_id=client_action_id,
        text=narration.text,
    )
    envelope = ServerEnvelope(
        type="narration.push",
        payload=push.model_dump(by_alias=True),
    )
    await send(envelope.model_dump(by_alias=True))


def _is_stale_queued_actor_error(exc: Exception) -> bool:
    """Queue items are discarded only when the frozen actor is gone or rebound."""

    return isinstance(exc, (ActorResolutionError, ActorBindingError))


def _map_turn_error(exc: Exception) -> tuple[str, str, bool]:
    if isinstance(exc, AdjudicationValidationError):
        feedback = exc.result.to_feedback()
        return (
            feedback.code,
            feedback.player_safe_reason,
            feedback.repairability == "retry_with_latest_revision",
        )
    if isinstance(exc, TurnExecutionError):
        return exc.code, exc.public_message, exc.retryable
    if isinstance(exc, ActorResolutionError):
        return "ACTOR_NOT_CONTROLLED", "当前玩家没有可控制的局内角色", False
    if isinstance(exc, ActorBindingError):
        return "ACTOR_NOT_CONTROLLED", "当前玩家不能控制该局内角色", False
    if isinstance(exc, RevisionConflictError):
        return "REVISION_CONFLICT", "房间状态已被其他动作更新，请重试", True
    if isinstance(exc, SQLAlchemyError):
        return "DATABASE_CONFLICT", "动作提交发生数据库并发冲突，请重试", True
    # 模型调用的普通故障。叙事阶段的同类失败已经在 `_narrate` 里被包装成
    # TurnExecutionError，所以这两条实际认领的是规划阶段——那里此前什么分类都没有，
    # 一个 30 秒超时和「引擎内部炸了」共用同一个兜底码（#285）。
    #
    # 两句文案都明确「本次动作未生效」：这类失败发生在裁决提交规则引擎之前，
    # 没有任何权威效果落库，不能让玩家以为动作已经算数、只是缺一段叙事。
    if is_transient_model_error(exc):
        return (
            "MODEL_UPSTREAM_UNAVAILABLE",
            "主持模型暂时不可用，本次动作未生效，请重试",
            True,
        )
    if isinstance(exc, StructuredOutputError):
        return (
            "MODEL_OUTPUT_UNREADABLE",
            "主持模型返回了无法解读的结果，本次动作未生效，请重试",
            True,
        )

    message = str(exc)
    if "运行时不存在" in message:
        return "ROOM_RUNTIME_NOT_FOUND", "房间尚未建立可用的游戏运行时", True
    if "不是可提交动作的 InGame" in message:
        return "ROOM_NOT_ACTIONABLE", "房间当前状态不允许提交动作", False
    if isinstance(exc, (ContractError, ValidationError)):
        # 可重试。这是主持链上「模型这一次的输出没通过契约」的兜底桶，同一句话
        # 重说一遍常常就过了（#313 的实测：`TURN_CONTRACT_INVALID` 后原话重试成
        # 功）。标成不可重试只会让前端连重试按钮都不给，把一次非确定性失败变成
        # 玩家必须自己重新打字的死路。与上面 `MODEL_OUTPUT_UNREADABLE` 同源，
        # 重试语义也应当一致。
        #
        # 重试不会重复结算，但理由不是「什么都没落库」——`adjudication.select` /
        # `adjudication.post_roll` 上 `_emit_check_result` 就跑在引擎权威结算之后，
        # 它抛 ContractError 时检定其实已经定了。挡住重复结算的是引擎自己：重放
        # 同一次决定会撞上 `DECISION_ALREADY_SETTLED`（hard_reject），重放同一个
        # clientActionId 的动作则复用已提交结果。
        return "TURN_CONTRACT_INVALID", "本次动作未通过主持编排契约校验，请重试", True
    return "TURN_INTERNAL_ERROR", "本次动作处理失败，请稍后重试", True


def _turn_error_reason(exc: Exception) -> str:
    """Return a stable internal reason without logging model/player payloads."""

    if isinstance(exc, ValidationError):
        issues = exc.errors(include_url=False, include_context=False, include_input=False)
        return "; ".join(
            f"{'.'.join(str(part) for part in issue.get('loc', ()))}:{issue.get('type', 'unknown')}"
            for issue in issues
        )[:512]
    reason = " ".join(str(exc).split())
    return (reason or type(exc).__name__)[:512]


_CheckSuccessLevel = Literal["critical", "extreme", "hard", "regular", "failure", "fumble"]

_CHECK_DEGREE_TO_SUCCESS_LEVEL: dict[str, _CheckSuccessLevel] = {
    "critical_success": "critical",
    "extreme_success": "extreme",
    "hard_success": "hard",
    "regular_success": "regular",
    "failure": "failure",
    "fumble": "fumble",
}


async def _emit_check_result(
    db: AsyncSession,
    websocket: WebSocket,
    *,
    room_id: str,
    player_id: str,
    client_action_id: str,
    execution: AdjudicationExecution,
) -> None:
    """检定结算后把权威结果落库并单播给掷骰玩家（issue #310）。

    #226 移除旧的 `check.roll` 通道时，`check.result` 的发送侧一并没了，消费侧
    却全留着：DTO、`events` 落库、replay 读取、recent-history 拼装、SDK 类型、
    前端渲染。结果是权威掷骰只在骰子浮层里出现一次，浮层一关就什么都不剩，
    刷新重进更是无从恢复。这里把发送侧接回去。

    只在检定真正 `resolved` 时发：带奖惩骰选项的检定要等玩家做完决定才有终值，
    中途发等于把一个还会变的点数当成结果。

    单播不广播：`replay`（`service/room.py`）现有口径就是「`check.result` 只返回
    给对应玩家」，两侧必须一致，否则重进房间会看到和当时不一样的历史。
    """

    check_run = execution.check_run
    if check_run is None or check_run.status != "resolved":
        return
    # 有 post-roll 选项时终值在 `final_result`；没有时引擎在建 CheckRun 那一刻
    # 就把 `roll` 同时写进了 `final_result`。两者都没有说明契约被破坏了，不猜。
    final = check_run.final_result
    if final is None:
        raise ContractError("resolved 的 CheckRun 缺少 final_result")
    success_level = _CHECK_DEGREE_TO_SUCCESS_LEVEL.get(final.degree)
    if success_level is None:
        raise ContractError(f"未知的检定判定等级: {final.degree}")

    player = await room_service.get_player(db, player_id)
    character_name = await room_service.get_player_character_name(
        db,
        player_id,
        fallback=player.nickname if player is not None else "玩家",
    )
    payload = CheckResultPayload(
        player_id=player_id,
        client_action_id=client_action_id,
        skill=check_run.selected_skill_id,
        skill_name=check_run.selected_skill_name,
        character_name=character_name,
        roll_value=final.value,
        target_value=check_run.target_value,
        difficulty=check_run.difficulty,
        success_level=success_level,
        passed=final.passed,
        result=success_level,
        resolution_kind=check_run.resolution_kind,
        luck_spent=check_run.luck_spent,
    )
    recorded = await room_service.record_event(
        db,
        room_id,
        player_id,
        "check.result",
        payload.model_dump(by_alias=True, mode="json"),
        visibility="player_scoped",
        actor_id=None,
        scene_id=None,
        view_revision=execution.view_revision,
        # 同一次检定重放（断线重连后重复提交同一决定）不能落成两条历史。
        correlation_id=check_run.check_id,
    )
    if not recorded:
        return
    log_check_result(
        room_id=room_id,
        correlation_id=client_action_id,
        character_name=character_name,
        skill_name=check_run.selected_skill_name,
        target_value=check_run.target_value,
        roll_value=final.value,
        difficulty=check_run.difficulty,
        success_level=success_level,
        passed=final.passed,
    )
    await _send_to_player(
        websocket,
        ServerEnvelope(
            type="check.result",
            payload=payload.model_dump(by_alias=True),
        ).model_dump(by_alias=True),
    )


async def _broadcast_action_utterance(
    db: AsyncSession,
    player_input: PlayerInput,
    player_view: PlayerView,
) -> None:
    """广播玩家原话，但不把讨论区消息混入叙事事件历史。"""

    # @NPC 的原话必须落成对话事件，而不是继续塞进 action.broadcast；主持仍然统一
    # 处理意图，但历史和回放要能把“说给谁听”单独拿出来。
    if player_input.interlocutor_id is not None:
        player = await room_service.get_player(db, player_input.player_id)
        nickname = player.nickname if player is not None else "玩家"
        audience_player_ids, _ = await _npc_dialogue_audience(
            db,
            room_id=player_input.room_id,
            scene_id=player_view.scene.id,
        )
        await npc_dialogue_service.persist_player_dialogue(
            db,
            view=player_view,
            player_id=player_input.player_id,
            actor_id=player_input.actor_id,
            client_action_id=player_input.client_action_id,
            utterance=player_input.utterance,
            interlocutor_id=player_input.interlocutor_id,
            audience_player_ids=audience_player_ids,
            nickname=nickname,
        )
        event = await room_service.get_correlated_event(
            db,
            player_input.room_id,
            "dialogue.player",
            f"{player_input.client_action_id}:player",
        )
        if event is not None:
            await _broadcast_dialogue_event(db, event, audience_player_ids)
        return

    await _broadcast_action_line(
        db,
        room_id=player_input.room_id,
        player_id=player_input.player_id,
        client_action_id=player_input.client_action_id,
        utterance=player_input.utterance,
        actor_id=player_input.actor_id,
        scene_id=player_view.scene_id,
        view_revision=player_view.revision,
        player_view=player_view,
    )


async def _broadcast_action_line(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
    client_action_id: str,
    utterance: str,
    actor_id: str | None,
    scene_id: str | None,
    view_revision: str | None,
    player_view: PlayerView | None = None,
) -> None:
    """把行动区原话广播给全房间，不进入主持主链。"""

    player = await room_service.get_player(db, player_id)
    nickname = player.nickname if player is not None else "玩家"
    character_name = await room_service.get_player_character_name(
        db,
        player_id,
        fallback=nickname,
    )
    listener_ids = (
        _listener_ids_for_utterance(utterance, player_view) if player_view is not None else ()
    )
    payload = ActionBroadcastPayload(
        player_id=player_id,
        client_action_id=client_action_id,
        nickname=nickname,
        character_name=character_name,
        utterance=utterance,
        speaker_id=actor_id,
        listener_ids=listener_ids,
        participant_ids=((actor_id,) if actor_id else ()) + listener_ids,
    )
    recorded = await room_service.record_event(
        db,
        room_id,
        player_id,
        "action.broadcast",
        payload.model_dump(by_alias=True, mode="json"),
        visibility="public",
        actor_id=actor_id,
        scene_id=scene_id,
        view_revision=view_revision,
        correlation_id=client_action_id,
    )
    if not recorded:
        return
    log_player_input(
        room_id=room_id,
        player_id=player_id,
        character_name=character_name,
        correlation_id=client_action_id,
        utterance=utterance,
    )
    envelope = ServerEnvelope(
        type="action.broadcast",
        payload=payload.model_dump(by_alias=True),
    )
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))


async def _handle_chat_send(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str,
    payload: ChatSendPayload,
) -> None:
    """落库并广播讨论区消息；该消息永远不进入 Host Agent 上下文。"""

    text = payload.text.strip()
    if not text:
        return
    player = await room_service.get_player(db, player_id)
    if player is None or player.room_id != room_id:
        return
    room = await room_service.find_room_by_id(db, room_id)
    if room.phase == "Completed":
        await _send_error(websocket, "FORBIDDEN", "游戏已结束，无法发送消息")
        return
    message = await chat_service.save_chat_message(
        db,
        room_id,
        player_id,
        text,
        payload.client_message_id,
        channel="discussion",
    )
    # 幂等键跨两个聊天入口共享；若旧请求已经落成 roleplay，广播必须忠实返回
    # 数据库中的原消息，不能按本次 chat.send 入口伪造频道或角色身份。
    actor_name = (
        await room_service.get_player_character_name(db, player_id, fallback=player.nickname)
        if message.channel == "roleplay"
        else None
    )
    chat_payload = ChatMessagePayload(
        message_id=message.id,
        player_id=message.player_id,
        nickname=player.nickname,
        channel=cast(Literal["discussion", "roleplay"], message.channel),
        actor_id=message.actor_id,
        actor_name=actor_name,
        text=message.text,
        sent_at=message.created_at,
        client_message_id=message.client_message_id,
    )
    envelope = ServerEnvelope(
        type="chat.message",
        payload=chat_payload.model_dump(by_alias=True, mode="json"),
    )
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))


async def _handle_action_chat_send(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str,
    payload: ChatSendPayload,
) -> None:
    """多人行动区普通消息：保存为角色扮演聊天，不进入事件或 Host 上下文。"""

    text = payload.text.strip()
    if not text:
        return
    player = await room_service.get_player(db, player_id)
    if player is None or player.room_id != room_id:
        return
    room = await room_service.find_room_by_id(db, room_id)
    if room.phase == "Completed":
        await _send_error(websocket, "FORBIDDEN", "游戏已结束，无法发送消息")
        return
    if room.max_players == 1:
        await _send_error(
            websocket,
            "BAD_REQUEST",
            "单人游戏行动区输入应提交给守秘人",
            correlation_id=payload.client_message_id,
        )
        return
    try:
        view = await session_view_application.current_player_view(
            room_id=room_id,
            player_id=player_id,
        )
    except Exception:
        await _send_error(
            websocket,
            "BAD_REQUEST",
            "当前无法确认角色身份，请稍后重试",
            correlation_id=payload.client_message_id,
        )
        return
    message = await chat_service.save_chat_message(
        db,
        room_id,
        player_id,
        text,
        payload.client_message_id,
        channel="roleplay",
        actor_id=view.self_actor.id,
    )
    # 重试若撞到同一玩家先前的 discussion 消息，以已落库频道为准，避免
    # 返回 roleplay + 空 actor 或 discussion + 非空 actor 的非法组合。
    actor_name = (
        await room_service.get_player_character_name(db, player_id, fallback=player.nickname)
        if message.channel == "roleplay"
        else None
    )
    chat_payload = ChatMessagePayload(
        message_id=message.id,
        player_id=message.player_id,
        nickname=player.nickname,
        channel=cast(Literal["discussion", "roleplay"], message.channel),
        actor_id=message.actor_id,
        actor_name=actor_name,
        text=message.text,
        sent_at=message.created_at,
        client_message_id=message.client_message_id,
    )
    await manager.broadcast(
        room_id,
        ServerEnvelope(
            type="chat.message",
            payload=chat_payload.model_dump(by_alias=True, mode="json"),
        ).model_dump(by_alias=True),
    )


async def _handle_room_join(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str | None,
    reconnect_token: str,
    authenticated_user_id: str,
) -> bool:
    """处理 room.join：校验 playerId 属于这个房间、且出示了该玩家的
    reconnect_token（证明是本人，不是拿别人 playerId 冒充），成功后登记连接并回
    session.bound。返回是否绑定成功。
    """
    player = await room_service.get_player(db, player_id) if player_id else None
    if (
        player is None
        or player.room_id != room_id
        or player.user_id != authenticated_user_id
        or player.reconnect_token != reconnect_token
    ):
        await websocket.close(code=_NOT_FOUND_CLOSE_CODE)
        return False
    assert player_id is not None  # 上面能走到这里，player_id 必然非空（见 get_player 调用）
    manager.add(room_id, player_id, websocket)
    await room_service.set_player_connected(db, player_id, True)
    payload = SessionBoundPayload(room_id=room_id, player_id=player_id)
    envelope = ServerEnvelope(type="session.bound", payload=payload.model_dump(by_alias=True))
    await websocket.send_json(envelope.model_dump(by_alias=True))
    return True


@router.websocket("/ws/{room_id}")
async def room_socket(websocket: WebSocket, room_id: str, token: str | None = None) -> None:
    # 鉴权只用一个短 session，用完立刻释放。**不要用一个 session 包住整条连接
    # 的生命周期**——那样会在整个 WebSocket 存续期间一直占着一个数据库连接/
    # 事务，跟并发的 HTTP 请求争抢 SQLite 的锁（在测试里表现为 HTTP 请求、或者
    # 用例结束时的建表/删表拿不到连接而死锁）。下面每条消息各开各的短 session。
    async with _short_db_session() as db:
        try:
            authenticated_user = await auth_service.get_me(db, token)
        except auth_service.AuthenticationError:
            await websocket.close(code=_UNAUTHORIZED_CLOSE_CODE)
            return

    await websocket.accept()
    bound_player_id: str | None = None

    try:
        while True:
            raw = await websocket.receive_json()

            # 信封校验不碰数据库，放在开 session 之前。一条信封本身就不合法的
            # 消息（不是对象、type 缺失等）只丢弃这一条，不打断整条连接。
            try:
                client_envelope = ClientEnvelope.model_validate(raw)
            except ValidationError as exc:
                bad_type = raw.get("type") if isinstance(raw, dict) else None
                logger.warning(
                    "ws_invalid_message",
                    event_type=bad_type,
                    validation_error_count=exc.error_count(),
                )
                continue

            event_type = client_envelope.type
            player_id = client_envelope.player_id
            raw_payload = client_envelope.payload

            # 每条消息各开一个短 session，处理完立刻释放——WebSocket 在两条消息
            # 之间等待（receive_json 阻塞）时不持有任何数据库连接。
            async with _short_db_session() as db:
                try:
                    if event_type == "room.join":
                        join_payload = RoomJoinPayload.model_validate(raw_payload)
                        if await _handle_room_join(
                            db,
                            websocket,
                            room_id,
                            player_id,
                            join_payload.reconnect_token,
                            authenticated_user.user_id,
                        ):
                            bound_player_id = player_id
                            assert bound_player_id is not None
                            current_view = None
                            try:
                                current_view = await session_view_application.current_player_view(
                                    room_id=room_id,
                                    player_id=bound_player_id,
                                )
                            except Exception:
                                # Lobby/Building rooms do not have an Engine
                                # runtime yet. Joining remains valid; game.start
                                # will send the initial view once it exists.
                                pass
                            else:
                                await _send_view_updated(
                                    websocket,
                                    bound_player_id,
                                    current_view,
                                )
                                await _send_room_action_state(db, websocket, room_id)
                                schedule_host_action_drain(room_id)
                            # Registering the socket happens inside _handle_room_join
                            # before this lookup. Together with broadcast-after-commit,
                            # that ordering guarantees a reconnecting client receives
                            # either the live opening or this persisted replay.
                            active_plan = await action_plan_turn_application.active_for_room(
                                room_id
                            )
                            pending_time = None
                            if (
                                current_view is not None
                                and active_plan is not None
                                and active_plan.status == "awaiting_time_consent"
                            ):
                                pending_time = await time_advance_service.get_pending(
                                    db,
                                    room_id,
                                    engine=adjudication_engine_service,
                                )
                            pending_scene = await scene_transition_service.get_pending(
                                db,
                                room_id,
                                engine=adjudication_engine_service,
                            )
                            # 先完成所有恢复查询，再发应用层可能立即关闭连接的
                            # 权威开场，避免取消落在 SQLite cursor 中间。
                            await _send_persisted_opening(db, websocket, room_id)
                            if pending_time is not None:
                                event_type = (
                                    "time.advance.pending"
                                    if isinstance(pending_time, TimeAdvancePendingPayload)
                                    else "time.advance.resolved"
                                )
                                await _send_to_player(
                                    websocket,
                                    ServerEnvelope(
                                        type=event_type,
                                        payload=pending_time.model_dump(
                                            by_alias=True,
                                            mode="json",
                                        ),
                                    ).model_dump(by_alias=True),
                                )
                            if pending_scene is not None:
                                event_type = (
                                    "scene.transition.pending"
                                    if isinstance(pending_scene, SceneTransitionPendingPayload)
                                    else "scene.transition.resolved"
                                )
                                await _send_to_player(
                                    websocket,
                                    ServerEnvelope(
                                        type=event_type,
                                        payload=pending_scene.model_dump(
                                            by_alias=True,
                                            mode="json",
                                        ),
                                    ).model_dump(by_alias=True),
                                )
                            if active_plan is not None and active_plan.player_id == bound_player_id:
                                if (
                                    active_plan.status
                                    in {
                                        "awaiting_time_consent",
                                        "awaiting_scene_consent",
                                    }
                                    and not isinstance(
                                        pending_time,
                                        TimeAdvancePendingPayload,
                                    )
                                    and not isinstance(
                                        pending_scene,
                                        SceneTransitionPendingPayload,
                                    )
                                ):
                                    # 服务在 Engine 提交后、PlanRun 恢复前退出时，
                                    # 重连作为恢复 worker 继续原计划并生成叙事。
                                    recovered = await action_plan_turn_application.resume_owned(
                                        room_id=room_id,
                                        player_id=bound_player_id,
                                        parent_action_id=active_plan.parent_action_id,
                                        on_progress=lambda event: _send_plan_progress(
                                            websocket,
                                            event,
                                        ),
                                    )
                                    await _send_action_plan_result(
                                        db,
                                        websocket,
                                        room_id,
                                        bound_player_id,
                                        recovered,
                                    )
                                elif active_plan.pending_cancel_request_id is not None:
                                    # A reconnect is also a recovery worker. The
                                    # durable intent owns the Engine command;
                                    # never replay the stale post-roll menu.
                                    recovered = await action_plan_turn_application.resume_owned(
                                        room_id=room_id,
                                        player_id=bound_player_id,
                                        parent_action_id=active_plan.parent_action_id,
                                        on_progress=lambda event: _send_plan_progress(
                                            websocket,
                                            event,
                                        ),
                                    )
                                    await _send_action_plan_result(
                                        db,
                                        websocket,
                                        room_id,
                                        bound_player_id,
                                        recovered,
                                    )
                                else:
                                    await _send_plan_progress(
                                        websocket,
                                        type(
                                            "RecoveredPlanProgress",
                                            (),
                                            {
                                                "type": "plan.step_changed",
                                                "correlation_id": active_plan.parent_action_id,
                                                "current_step": min(
                                                    active_plan.current_step_index + 1,
                                                    len(active_plan.steps),
                                                ),
                                                "completed_steps": active_plan.completed_steps,
                                                "total_steps": len(active_plan.steps),
                                                "phase": (
                                                    "waiting_for_player"
                                                    if active_plan.status
                                                    in {
                                                        "waiting_for_player",
                                                        "awaiting_time_consent",
                                                        "awaiting_scene_consent",
                                                    }
                                                    else "understanding"
                                                ),
                                                "public_progress_label": None,
                                                "safe_reason": None,
                                            },
                                        )(),
                                    )
                                    if active_plan.status == "waiting_for_player":
                                        execution = active_plan.steps[
                                            active_plan.current_step_index
                                        ].adjudication_execution
                                        if execution is not None:
                                            pending = AdjudicationPendingPayload(
                                                correlation_id=active_plan.parent_action_id,
                                                plan_id=active_plan.plan_id,
                                                source_revision=execution.view_revision,
                                                status=_require_pending_adjudication_status(
                                                    execution.status
                                                ),
                                                pending_decision=execution.pending_decision,
                                                check_run=execution.check_run,
                                            )
                                            await _send_to_player(
                                                websocket,
                                                ServerEnvelope(
                                                    type="adjudication.pending",
                                                    payload=pending.model_dump(
                                                        by_alias=True,
                                                        mode="json",
                                                    ),
                                                ).model_dump(by_alias=True),
                                            )
                            else:
                                legacy_request_id = (
                                    await adjudication_engine_service.find_active_action_for_player(
                                        room_id=room_id,
                                        player_id=bound_player_id,
                                    )
                                )
                                if legacy_request_id is not None:
                                    recovery = await legacy_single_action_recovery.recover(
                                        GetAdjudicationStatusRequest(
                                            room_id=room_id,
                                            player_id=bound_player_id,
                                            action_request_id=legacy_request_id,
                                        )
                                    )
                                    if recovery is not None and recovery.execution.status in {
                                        "awaiting_skill_choice",
                                        "awaiting_post_roll_decision",
                                    }:
                                        execution = recovery.execution
                                        pending = AdjudicationPendingPayload(
                                            correlation_id=legacy_request_id,
                                            plan_id=None,
                                            source_revision=execution.view_revision,
                                            status=_require_pending_adjudication_status(
                                                execution.status
                                            ),
                                            pending_decision=execution.pending_decision,
                                            check_run=execution.check_run,
                                        )
                                        await _send_to_player(
                                            websocket,
                                            ServerEnvelope(
                                                type="adjudication.pending",
                                                payload=pending.model_dump(
                                                    by_alias=True,
                                                    mode="json",
                                                ),
                                            ).model_dump(by_alias=True),
                                        )
                                    else:
                                        logger.error(
                                            "turn_run_missing_on_reconnect",
                                            room=room_id,
                                            player=bound_player_id,
                                            action=legacy_request_id,
                                            reason="engine_action_not_legacy_eligible",
                                        )
                                        await _send_error(
                                            websocket,
                                            "PLAN_RUN_MISSING",
                                            "行动运行记录缺失，无法安全恢复；请重新提交行动",
                                            correlation_id=legacy_request_id,
                                        )
                        else:
                            return
                        continue

                    if bound_player_id is None:
                        # 还没完成 room.join 绑定，忽略这条消息，不让未识别身份的
                        # 连接影响房间状态。
                        continue

                    if event_type == "player.ready":
                        ready_payload = PlayerReadyPayload.model_validate(raw_payload)
                        await room_service.set_player_ready(
                            db, bound_player_id, ready_payload.ready
                        )
                        await broadcast_room_state(db, room_id)
                    elif event_type == "game.start":
                        GameStartPayload.model_validate(raw_payload)
                        try:
                            await room_service.begin_game(db, room_id, bound_player_id)
                        except room_service.RoomAuthorizationError as exc:
                            await _send_error(websocket, "FORBIDDEN", str(exc))
                            continue
                        except room_service.CharacterIncompleteError as exc:
                            await _send_error(websocket, "CHARACTER_INCOMPLETE", str(exc))
                            continue
                        except (
                            room_service.RoomNotFoundError,
                            room_service.RoomConflictError,
                        ) as exc:
                            await _send_error(websocket, "CONFLICT", str(exc))
                            continue
                        initial_view = await session_view_application.current_player_view(
                            room_id=room_id,
                            player_id=bound_player_id,
                        )
                        await _broadcast_player_views(room_id)
                        await _broadcast_room_action_state(db, room_id)
                        await broadcast_room_state(db, room_id)
                        await _ensure_opening_narration(
                            db,
                            room_id,
                            initial_view,
                        )
                    elif event_type == "chat.send":
                        chat_payload = ChatSendPayload.model_validate(raw_payload)
                        await _handle_chat_send(
                            db,
                            websocket,
                            room_id,
                            bound_player_id,
                            chat_payload,
                        )
                    elif event_type == "action.chat.send":
                        action_chat = ChatSendPayload.model_validate(raw_payload)
                        await _handle_action_chat_send(
                            db,
                            websocket,
                            room_id,
                            bound_player_id,
                            action_chat,
                        )
                    elif event_type == "time.advance.respond":
                        response_payload = TimeAdvanceRespondPayload.model_validate(raw_payload)
                        try:
                            (
                                result,
                                resume_player_id,
                                action_request_id,
                            ) = await time_advance_service.respond(
                                db,
                                engine=adjudication_engine_service,
                                room_id=room_id,
                                player_id=bound_player_id,
                                proposal_id=response_payload.proposal_id,
                                proposal_version=response_payload.proposal_version,
                                source_revision=response_payload.source_revision,
                                accept=response_payload.accept,
                            )
                        except time_advance_service.TimeAdvanceError as exc:
                            await _send_error(websocket, "TIME_ADVANCE_CONFLICT", str(exc))
                            continue
                        await _broadcast_time_advance(room_id, result)
                        if resume_player_id is not None and action_request_id is not None:
                            await _broadcast_room_action_state(
                                db,
                                room_id,
                                force_processing=True,
                            )
                            resumed = await _resume_after_authoritative_decision(
                                db,
                                room_id=room_id,
                                player_id=resume_player_id,
                                parent_action_id=action_request_id,
                            )
                            # 最后一票可能来自队友，语叙和私有视图必须发给原行动者。
                            for target_socket in manager.player_connections(
                                room_id,
                                resume_player_id,
                            ):
                                await _send_action_plan_result(
                                    db,
                                    target_socket,
                                    room_id,
                                    resume_player_id,
                                    resumed,
                                )
                    elif event_type == "scene.transition.respond":
                        response_payload = SceneTransitionRespondPayload.model_validate(raw_payload)
                        try:
                            (
                                result,
                                resume_player_id,
                                action_request_id,
                            ) = await scene_transition_service.respond(
                                db,
                                engine=adjudication_engine_service,
                                room_id=room_id,
                                player_id=bound_player_id,
                                proposal_id=response_payload.proposal_id,
                                proposal_version=response_payload.proposal_version,
                                source_revision=response_payload.source_revision,
                                accept=response_payload.accept,
                            )
                        except scene_transition_service.SceneTransitionError as exc:
                            await _send_error(websocket, "SCENE_TRANSITION_CONFLICT", str(exc))
                            continue
                        await _broadcast_scene_transition(room_id, result)
                        if resume_player_id is not None and action_request_id is not None:
                            await _broadcast_room_action_state(
                                db,
                                room_id,
                                force_processing=True,
                            )
                            resumed = await action_plan_turn_application.resume_pending(
                                room_id=room_id,
                                player_id=resume_player_id,
                                parent_action_id=action_request_id,
                            )
                            for target_socket in manager.player_connections(
                                room_id,
                                resume_player_id,
                            ):
                                await _send_action_plan_result(
                                    db,
                                    target_socket,
                                    room_id,
                                    resume_player_id,
                                    resumed,
                                )
                    elif event_type == "action.plan.submit":
                        submit_payload = ActionSubmitPayload.model_validate(raw_payload)
                        room = await room_service.find_room_by_id(db, room_id)
                        if room.max_players > 1 and not submit_payload.recipient.explicit:
                            await _send_error(
                                websocket,
                                "BAD_REQUEST",
                                "多人游戏必须明确 @守秘人 后才能提交主持行动",
                                correlation_id=submit_payload.client_action_id,
                            )
                            continue
                        if submit_payload.visibility == "private":
                            await _send_error(
                                websocket,
                                "NOT_IMPLEMENTED",
                                "私密行动本期尚未实现",
                                correlation_id=submit_payload.client_action_id,
                            )
                            continue
                        if await _recover_persisted_turn_narration(
                            db,
                            websocket,
                            room_id=room_id,
                            player_id=bound_player_id,
                            client_action_id=submit_payload.client_action_id,
                        ):
                            continue
                        try:
                            action_view = await session_view_application.current_player_view(
                                room_id=room_id,
                                player_id=bound_player_id,
                            )
                        except Exception as exc:
                            # 尚未建立游戏运行时等前置失败不会取得房间锁；向发起者返回
                            # 原有 turn.failed，并保持连接可立即重试。
                            await _send_turn_failed(
                                websocket,
                                submit_payload.client_action_id,
                                exc,
                            )
                            continue
                        if submit_payload.recipient.kind == "npc":
                            try:
                                require_dialogue_npc(
                                    action_view,
                                    submit_payload.recipient.entity_id or "",
                                )
                            except ValueError as exc:
                                await _send_error(
                                    websocket,
                                    "VALIDATION_ERROR",
                                    str(exc),
                                    correlation_id=submit_payload.client_action_id,
                                )
                                continue
                            occupancy = await _current_room_action_state(db, room_id)
                            decision = await _queue_decision_for_submit(
                                db,
                                room_id=room_id,
                                player_id=bound_player_id,
                                client_action_id=submit_payload.client_action_id,
                                state=occupancy,
                            )
                            if decision == "enqueue":
                                await _enqueue_host_action(
                                    db,
                                    websocket,
                                    room_id=room_id,
                                    player_id=bound_player_id,
                                    actor_id=action_view.self_actor.id,
                                    client_action_id=submit_payload.client_action_id,
                                    utterance=submit_payload.utterance,
                                    player_view=action_view,
                                    recipient=submit_payload.recipient,
                                )
                                schedule_host_action_drain(room_id)
                                continue
                            if decision == "reject":
                                await _send_error(
                                    websocket,
                                    "ACTION_IN_PROGRESS",
                                    "请先完成或取消当前检定/确认，再提交新的主持行动",
                                    correlation_id=submit_payload.client_action_id,
                                )
                                continue
                        occupancy = await _current_room_action_state(db, room_id)
                        decision = await _queue_decision_for_submit(
                            db,
                            room_id=room_id,
                            player_id=bound_player_id,
                            client_action_id=submit_payload.client_action_id,
                            state=occupancy,
                        )
                        if decision == "enqueue":
                            await _enqueue_host_action(
                                db,
                                websocket,
                                room_id=room_id,
                                player_id=bound_player_id,
                                actor_id=action_view.self_actor.id,
                                client_action_id=submit_payload.client_action_id,
                                utterance=submit_payload.utterance,
                                player_view=action_view,
                                recipient=submit_payload.recipient,
                            )
                            continue
                        if decision == "reject":
                            await _send_error(
                                websocket,
                                "ACTION_IN_PROGRESS",
                                "请先完成或取消当前检定/确认，再提交新的主持行动",
                                correlation_id=submit_payload.client_action_id,
                            )
                            continue
                        lock_token = action_lock_manager.try_acquire(
                            room_id,
                            player_id=bound_player_id,
                            actor_id=action_view.self_actor.id,
                            client_action_id=submit_payload.client_action_id,
                            revision=action_view.revision,
                        )
                        if lock_token is None:
                            await _enqueue_host_action(
                                db,
                                websocket,
                                room_id=room_id,
                                player_id=bound_player_id,
                                actor_id=action_view.self_actor.id,
                                client_action_id=submit_payload.client_action_id,
                                utterance=submit_payload.utterance,
                                player_view=action_view,
                                recipient=submit_payload.recipient,
                            )
                            continue
                        try:
                            active_plan = await action_plan_turn_application.active_for_room(
                                room_id
                            )
                            if (
                                active_plan is not None
                                and active_plan.parent_action_id != submit_payload.client_action_id
                                # `retryable_failure` 与 `needs_clarification` 同构：两者都停在
                                # 等这名玩家再说一句上。此前只豁免后者，于是一次瞬态失败之后，
                                # 本人换个说法就被自己那条死计划挡住——只有原样重发同一个
                                # client_action_id 才放行，等于「换句话说」被永久禁用。
                                and not (
                                    active_plan.status
                                    in ("needs_clarification", "retryable_failure")
                                    and active_plan.player_id == bound_player_id
                                )
                            ):
                                action_lock_manager.release(room_id, lock_token)
                                await _enqueue_host_action(
                                    db,
                                    websocket,
                                    room_id=room_id,
                                    player_id=bound_player_id,
                                    actor_id=action_view.self_actor.id,
                                    client_action_id=submit_payload.client_action_id,
                                    utterance=submit_payload.utterance,
                                    player_view=action_view,
                                    recipient=submit_payload.recipient,
                                )
                                continue
                            await _send_turn_event(
                                websocket,
                                TurnStarted(correlation_id=submit_payload.client_action_id),
                            )
                            turn_started_at = time.monotonic()
                            await _broadcast_room_action_state(db, room_id)
                            result = await action_plan_turn_application.start(
                                room_id=room_id,
                                player_id=bound_player_id,
                                client_action_id=submit_payload.client_action_id,
                                utterance=submit_payload.utterance,
                                interlocutor_id=(
                                    submit_payload.recipient.entity_id
                                    if submit_payload.recipient.kind == "npc"
                                    else None
                                ),
                                interlocutor_name=(
                                    require_dialogue_npc(
                                        action_view,
                                        submit_payload.recipient.entity_id or "",
                                    ).name
                                    if submit_payload.recipient.kind == "npc"
                                    else None
                                ),
                                on_progress=lambda event: _send_plan_progress(
                                    websocket,
                                    event,
                                ),
                                on_phase=partial(
                                    _send_turn_phase,
                                    websocket,
                                    submit_payload.client_action_id,
                                ),
                                on_input_accepted=partial(
                                    _broadcast_action_utterance,
                                    db,
                                ),
                            )
                            narration_ready_ms = (
                                int((time.monotonic() - turn_started_at) * 1000)
                                if result.narration is not None
                                else None
                            )

                            async def _release_action_before_completed(
                                token: str = lock_token,
                            ) -> None:
                                with anyio.CancelScope(shield=True):
                                    action_lock_manager.release(room_id, token)
                                    await _broadcast_room_action_state_fresh(room_id)

                            await _send_action_plan_result(
                                db,
                                websocket,
                                room_id,
                                bound_player_id,
                                result,
                                before_completed=(
                                    _release_action_before_completed
                                    if not result.waiting_for_player
                                    else None
                                ),
                            )
                            completed_ms = int((time.monotonic() - turn_started_at) * 1000)
                            log_action_plan_latency(
                                room_id=room_id,
                                correlation_id=submit_payload.client_action_id,
                                status=result.status,
                                time_to_waiting_check_ms=(
                                    completed_ms if result.waiting_for_player else None
                                ),
                                time_to_first_narration_ms=narration_ready_ms,
                                time_to_final_narration_ms=(
                                    completed_ms if result.narration is not None else None
                                ),
                                end_to_end_ms=completed_ms,
                            )
                        except Exception as exc:
                            code, _, _ = _map_turn_error(exc)
                            log_turn_failed(
                                room_id=room_id,
                                stage="行动计划",
                                code=code,
                                correlation_id=submit_payload.client_action_id,
                                error_type=type(exc).__name__,
                                error_reason=_turn_error_reason(exc),
                                exc=exc,
                            )
                            await _send_turn_failed(
                                websocket,
                                submit_payload.client_action_id,
                                exc,
                            )
                        finally:
                            # 最终叙事到达后连接可能立刻关闭；仍须按 token 释放锁并
                            # 广播 idle，避免旧行动长期阻塞房间。
                            with anyio.CancelScope(shield=True):
                                action_lock_manager.release(room_id, lock_token)
                                await _broadcast_room_action_state_fresh(room_id)
                            schedule_host_action_drain(room_id)
                    elif event_type == "adjudication.select":
                        choice = AdjudicationChoicePayload.model_validate(raw_payload)
                        if choice.cancel:
                            selected = CancelCheckChoice()
                        elif choice.candidate_id is not None:
                            selected = SelectCheckChoice(candidate_id=choice.candidate_id)
                        else:
                            await _send_error(
                                websocket,
                                "INVALID_CHOICE",
                                "必须选择一个技能或取消当前检定",
                                correlation_id=choice.client_action_id,
                            )
                            continue
                        try:
                            await _broadcast_room_action_state(
                                db,
                                room_id,
                                force_processing=True,
                            )
                            execution = await _check_decision_engine().decide(
                                CheckDecisionRequest(
                                    request_id=choice.request_id,
                                    room_id=room_id,
                                    player_id=bound_player_id,
                                    source_revision=choice.source_revision,
                                    decision_id=choice.decision_id,
                                    decision_version=choice.decision_version,
                                    choice=selected,
                                )
                            )
                            # 没有奖惩骰选项的检定在这一步就定了终值。
                            await _emit_check_result(
                                db,
                                websocket,
                                room_id=room_id,
                                player_id=bound_player_id,
                                client_action_id=choice.client_action_id,
                                execution=execution,
                            )
                            if await _recover_persisted_turn_narration(
                                db,
                                websocket,
                                room_id=room_id,
                                player_id=bound_player_id,
                                client_action_id=choice.client_action_id,
                            ):
                                continue
                            result = await _resume_after_authoritative_decision(
                                db,
                                room_id=room_id,
                                player_id=bound_player_id,
                                parent_action_id=choice.client_action_id,
                                on_progress=lambda event: _send_plan_progress(
                                    websocket,
                                    event,
                                ),
                                on_phase=partial(
                                    _send_turn_phase,
                                    websocket,
                                    choice.client_action_id,
                                ),
                            )
                            await _send_action_plan_result(
                                db,
                                websocket,
                                room_id,
                                bound_player_id,
                                result,
                            )
                        except Exception as exc:
                            code, _, _ = _map_turn_error(exc)
                            log_turn_failed(
                                room_id=room_id,
                                stage="检定选择",
                                code=code,
                                correlation_id=choice.client_action_id,
                                error_type=type(exc).__name__,
                                error_reason=_turn_error_reason(exc),
                                exc=exc,
                            )
                            await _send_turn_failed(websocket, choice.client_action_id, exc)
                            await _broadcast_room_action_state(db, room_id)
                    elif event_type == "adjudication.post_roll":
                        choice = AdjudicationPostRollPayload.model_validate(raw_payload)
                        try:
                            await _broadcast_room_action_state(
                                db,
                                room_id,
                                force_processing=True,
                            )
                            execution = await _check_decision_engine().decide_post_roll(
                                PostRollDecisionRequest(
                                    request_id=choice.request_id,
                                    room_id=room_id,
                                    player_id=bound_player_id,
                                    source_revision=choice.source_revision,
                                    check_id=choice.check_id,
                                    check_version=choice.check_version,
                                    option_id=choice.option_id,
                                    push_adjudication=(
                                        PushAdjudication(method_description=choice.revised_method)
                                        if choice.revised_method is not None
                                        else None
                                    ),
                                )
                            )
                            # 奖惩骰/孤注一掷做完决定，这一步才有终值。
                            await _emit_check_result(
                                db,
                                websocket,
                                room_id=room_id,
                                player_id=bound_player_id,
                                client_action_id=choice.client_action_id,
                                execution=execution,
                            )
                            if await _recover_persisted_turn_narration(
                                db,
                                websocket,
                                room_id=room_id,
                                player_id=bound_player_id,
                                client_action_id=choice.client_action_id,
                            ):
                                continue
                            result = await _resume_after_authoritative_decision(
                                db,
                                room_id=room_id,
                                player_id=bound_player_id,
                                parent_action_id=choice.client_action_id,
                                on_progress=lambda event: _send_plan_progress(
                                    websocket,
                                    event,
                                ),
                                on_phase=partial(
                                    _send_turn_phase,
                                    websocket,
                                    choice.client_action_id,
                                ),
                            )
                            await _send_action_plan_result(
                                db,
                                websocket,
                                room_id,
                                bound_player_id,
                                result,
                            )
                        except Exception as exc:
                            code, _, _ = _map_turn_error(exc)
                            log_turn_failed(
                                room_id=room_id,
                                stage="检定后续",
                                code=code,
                                correlation_id=choice.client_action_id,
                                error_type=type(exc).__name__,
                                error_reason=_turn_error_reason(exc),
                                exc=exc,
                            )
                            await _send_turn_failed(websocket, choice.client_action_id, exc)
                            await _broadcast_room_action_state(db, room_id)
                    elif event_type == "action.plan.cancel":
                        cancel = ActionPlanCancelPayload.model_validate(raw_payload)
                        if await host_action_queue_service.cancel(
                            db,
                            room_id=room_id,
                            player_id=bound_player_id,
                            client_action_id=cancel.client_action_id,
                        ):
                            await _send_turn_event(
                                websocket,
                                TurnFailed(
                                    correlation_id=cancel.client_action_id,
                                    code="ACTION_CANCELLED",
                                    public_message="已取消排队中的主持行动",
                                    retryable=False,
                                ),
                            )
                            await _broadcast_room_action_state(db, room_id)
                            continue
                        try:
                            await _broadcast_room_action_state(
                                db,
                                room_id,
                                force_processing=True,
                            )
                            scene_aborted = await scene_transition_service.abort_pending(
                                db,
                                engine=adjudication_engine_service,
                                room_id=room_id,
                                player_id=bound_player_id,
                                parent_action_id=cancel.client_action_id,
                            )
                            if scene_aborted is not None:
                                await _broadcast_scene_transition(room_id, scene_aborted)
                            time_aborted = await time_advance_service.abort_pending(
                                db,
                                engine=adjudication_engine_service,
                                room_id=room_id,
                                player_id=bound_player_id,
                                parent_action_id=cancel.client_action_id,
                            )
                            if time_aborted is not None:
                                await _broadcast_time_advance(room_id, time_aborted)
                            result = await action_plan_turn_application.cancel_remaining(
                                room_id=room_id,
                                player_id=bound_player_id,
                                parent_action_id=cancel.client_action_id,
                                request_id=cancel.request_id,
                            )
                            await _send_action_plan_result(
                                db,
                                websocket,
                                room_id,
                                bound_player_id,
                                result,
                            )
                            schedule_host_action_drain(room_id)
                        except Exception as exc:
                            code, _, _ = _map_turn_error(exc)
                            log_turn_failed(
                                room_id=room_id,
                                stage="取消行动计划",
                                code=code,
                                correlation_id=cancel.client_action_id,
                                error_type=type(exc).__name__,
                                error_reason=_turn_error_reason(exc),
                                exc=exc,
                            )
                            await _send_turn_failed(websocket, cancel.client_action_id, exc)
                            await _broadcast_room_action_state(db, room_id)
                    elif event_type == "san.check.roll":
                        SanCheckRollPayload.model_validate(raw_payload)
                        await _send_error(
                            websocket, "NOT_IMPLEMENTED", "服务端权威理智检定本期尚未实现"
                        )
                    elif event_type == "room.rejoin":
                        RoomRejoinPayload.model_validate(raw_payload)
                        await _send_error(websocket, "NOT_IMPLEMENTED", "断线重连本期尚未实现")
                except ValidationError as exc:
                    # payload 层校验失败（信封 OK 但具体事件 payload 形状不对），
                    # 同样只丢弃这一条。event_type 此时必然已赋值。
                    logger.warning(
                        "ws_invalid_message",
                        event_type=event_type,
                        validation_error_count=exc.error_count(),
                    )
                    if event_type == "action.plan.submit":
                        correlation_id = raw_payload.get("clientActionId")
                        await _send_error(
                            websocket,
                            "VALIDATION_ERROR",
                            "行动接收者或输入格式无效",
                            correlation_id=(
                                correlation_id if isinstance(correlation_id, str) else None
                            ),
                        )
                    continue
    except WebSocketDisconnect:
        pass
    except RuntimeError as exc:
        # 广播可能先发现对端断开，使 send_json 把 application_state 标为
        # DISCONNECTED；随后当前连接的 receive_json 会抛 RuntimeError。
        # TestClient 的常规断连则通常直接抛 WebSocketDisconnect。
        #
        # 还有一种真实出现过的情况：底层 TCP 连接已经断开（例如玩家在等回复
        # 时刷新了页面），但 Starlette 的 application_state 要到下一次收到
        # receive 事件才会被标记为 DISCONNECTED——这时候是我们主动往一个已经
        # 关闭的 transport 上 send_json，直接从 uvloop 抛 RuntimeError（信息类似
        # "unable to perform operation on <TCPTransport closed=True ...>"），
        # application_state 这时候还看着像"已连接"。两种情况本质一样：这个连接
        # 已经联系不上了，没有客户端能收到接下来想发的任何消息，按断线处理即可。
        #
        # 判据与 `_send_to_player` 共用一个：单播帧被丢掉的条件，和整条连接被
        # 判定为断开的条件，必须是同一件事，否则两边会各自漂移。
        if not _connection_is_gone(websocket, exc):
            raise
    finally:
        manager.remove(room_id, websocket)
        # 断线清理另开一个短 session：上面每条消息用的 db 作用域已经结束，
        # 这里要把玩家标记为已断开，需要一个新的会话。
        if bound_player_id is not None:
            with anyio.CancelScope(shield=True):
                async with _short_db_session() as db:
                    await room_service.set_player_connected(db, bound_player_id, False)
