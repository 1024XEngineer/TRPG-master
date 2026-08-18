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
  普通叙事广播全房间，需要澄清的叙事只发给发起者；
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

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial
from typing import Literal

import anyio
import structlog
from collaboration_framework.contracts import (
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
from collaboration_framework.host.schemas import NarrationOutput
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from app.adapters.structured_http import StructuredOutputError, is_transient_model_error
from app.core.action_plan_turn import (
    ActionPlanTurnResult,
    action_plan_turn_application,
)
from app.core.db import async_session_factory
from app.core.engine import adjudication_engine_service
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
    log_check_result,
    log_narration_output,
    log_player_input,
    log_turn_failed,
)
from app.dto.ws import (
    ActionBroadcastPayload,
    ActionPlanCancelPayload,
    ActionSubmitPayload,
    AdjudicationChoicePayload,
    AdjudicationPendingPayload,
    AdjudicationPostRollPayload,
    ChatMessagePayload,
    ChatSendPayload,
    CheckResultPayload,
    ClientEnvelope,
    ErrorPayload,
    GameStartPayload,
    NarrationChunkPayload,
    NarrationPushPayload,
    OpeningStartedPayload,
    PlanProgressPayload,
    PlayerReadyPayload,
    RoomJoinPayload,
    RoomRejoinPayload,
    SanCheckRollPayload,
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
from app.service import auth as auth_service
from app.service import chat as chat_service
from app.service import room as room_service
from app.service import time_advance as time_advance_service
from app.service.action_lock import action_lock_manager
from app.service.ws_events import broadcast_room_state
from app.service.ws_manager import manager

router = APIRouter()
logger = structlog.get_logger()

_UNAUTHORIZED_CLOSE_CODE = 4401
_NOT_FOUND_CLOSE_CODE = 4404
_OPENING_MESSAGE_ID = "game-opening"


class _PersistedTurnCompletion(BaseModel):
    """Backend-only metadata needed to replay a completed turn exactly."""

    kind: Literal["narration", "clarification"] = "narration"
    claimed_fact_ids: tuple[str, ...] = ()
    suggested_actions: tuple[str, ...] = Field(default=(), max_length=3)


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


async def _send_to_player(websocket: WebSocket, message: dict) -> bool:
    """单播一帧；对端已经断了就丢掉这一帧，不打断正在跑的回合。

    回合是在收消息循环里内联跑完的，进度、阶段和结算帧都直接写这个 socket。
    玩家中途掉线/刷新时，这些 send 会抛异常并把回合从中间掐断——规则效果已经
    事务提交，叙事却还没落库（`_deliver_turn_narration` 在发送链的末尾），世界
    推进了但解释它的那段话永远消失。房间广播早就是容断的（见
    service/ws_manager.py 的 broadcast），单播这条通道之前不是。

    返回是否真的送达，让调用方能记日志；但**不构成控制流**：一个已经断开的
    连接不该影响这一回合能不能跑完、能不能落库。
    """

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


async def _send_turn_event(
    websocket: WebSocket,
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
    websocket: WebSocket,
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
    websocket: WebSocket,
    correlation_id: str,
    phase: TurnPhase,
) -> None:
    await _send_turn_event(
        websocket,
        TurnPhaseChanged(correlation_id=correlation_id, phase=phase),
    )


async def _send_plan_progress(websocket: WebSocket, event) -> None:
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
    websocket: WebSocket,
    room_id: str,
    player_id: str,
    result: ActionPlanTurnResult,
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
            await _broadcast_time_advance(room_id, pending_time)
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
    recorded = await _send_completed_turn_message(
        db,
        websocket,
        room_id,
        player_id,
        actor_id=result.player_input.actor_id,
        client_action_id=result.player_input.client_action_id,
        player_view=result.player_view,
        narration=output,
    )
    # 先确认权威 narration.push 已持久化，再关闭时间提案恢复锚点；若进程
    # 在两步之间退出，重连会重放既有叙事而不会重新推进世界时间。
    with anyio.CancelScope(shield=True):
        await time_advance_service.mark_narration_persisted(
            db,
            room_id=room_id,
            parent_action_id=result.player_input.client_action_id,
        )
    await action_plan_turn_application.mark_narration_persisted(
        room_id=room_id,
        parent_action_id=result.player_input.client_action_id,
        on_progress=lambda event: _send_plan_progress(websocket, event),
    )
    return recorded


async def _send_completed_turn_message(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str,
    *,
    actor_id: str,
    client_action_id: str,
    player_view: PlayerView,
    narration: NarrationOutput,
) -> bool:
    """Send one completed turn and persist its authoritative narration once."""

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
    recorded = await _deliver_turn_narration(
        db,
        websocket,
        room_id,
        player_id,
        client_action_id=client_action_id,
        narration=narration,
        actor_id=actor_id,
        scene_id=player_view.scene_id,
        view_revision=player_view.revision,
    )
    return recorded


async def _recover_persisted_turn_narration(
    db: AsyncSession,
    websocket: WebSocket,
    *,
    room_id: str,
    player_id: str,
    client_action_id: str,
) -> bool:
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
        recovery = await adjudication_engine_service.recover_action(
            GetAdjudicationStatusRequest(
                room_id=room_id,
                player_id=player_id,
                action_request_id=client_action_id,
            )
        )
        if recovery is None or recovery.execution.status not in {"resolved", "cancelled"}:
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
    await _send_view_updated(websocket, player_id, view)
    if active is not None:
        await action_plan_turn_application.mark_narration_persisted(
            room_id=room_id,
            parent_action_id=client_action_id,
            on_progress=lambda event: _send_plan_progress(websocket, event),
        )
    return True


async def _send_view_updated(
    websocket: WebSocket,
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


async def _deliver_turn_narration(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str,
    *,
    client_action_id: str,
    narration: NarrationOutput,
    actor_id: str,
    scene_id: str,
    view_revision: str,
) -> bool:
    """持久化去重成功后才发送一次动作叙事。"""

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
    }
    recorded = await room_service.record_event(
        db,
        room_id,
        player_id,
        "narration.push",
        payload,
        visibility="player_scoped" if completion.kind == "clarification" else "public",
        actor_id=actor_id,
        scene_id=scene_id,
        view_revision=view_revision,
        correlation_id=client_action_id,
    )
    if not recorded:
        return False
    log_narration_output(
        room_id=room_id,
        correlation_id=client_action_id,
        text=text,
        clarification=completion.kind == "clarification",
    )
    # 澄清叙事只对发起者可见，它的渐进片段必须走同一条投递通道，
    # 否则片段会广播给全房间、泄露只该给一个人看的内容。
    send = (
        partial(_send_to_player, websocket)
        if completion.kind == "clarification"
        else partial(manager.broadcast, room_id)
    )
    await _stream_narration_chunks(
        send,
        message_id=client_action_id,
        text=text,
    )
    envelope = ServerEnvelope(
        type="narration.push",
        payload=push.model_dump(by_alias=True),
    )
    await send(envelope.model_dump(by_alias=True))
    return True


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

    player = await room_service.get_player(db, player_input.player_id)
    nickname = player.nickname if player is not None else "玩家"
    character_name = await room_service.get_player_character_name(
        db,
        player_input.player_id,
        fallback=nickname,
    )
    payload = ActionBroadcastPayload(
        player_id=player_input.player_id,
        client_action_id=player_input.client_action_id,
        nickname=nickname,
        character_name=character_name,
        utterance=player_input.utterance,
    )
    recorded = await room_service.record_event(
        db,
        player_input.room_id,
        player_input.player_id,
        "action.broadcast",
        payload.model_dump(by_alias=True, mode="json"),
        visibility="public",
        actor_id=player_input.actor_id,
        scene_id=player_view.scene_id,
        view_revision=player_view.revision,
        correlation_id=player_input.client_action_id,
    )
    if not recorded:
        return
    log_player_input(
        room_id=player_input.room_id,
        player_id=player_input.player_id,
        character_name=character_name,
        correlation_id=player_input.client_action_id,
        utterance=player_input.utterance,
    )
    envelope = ServerEnvelope(
        type="action.broadcast",
        payload=payload.model_dump(by_alias=True),
    )
    await manager.broadcast(player_input.room_id, envelope.model_dump(by_alias=True))


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
    )
    chat_payload = ChatMessagePayload(
        message_id=message.id,
        player_id=message.player_id,
        nickname=player.nickname,
        text=message.text,
        sent_at=message.created_at,
        client_message_id=message.client_message_id,
    )
    envelope = ServerEnvelope(
        type="chat.message",
        payload=chat_payload.model_dump(by_alias=True, mode="json"),
    )
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))


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
                            # Registering the socket happens inside _handle_room_join
                            # before this lookup. Together with broadcast-after-commit,
                            # that ordering guarantees a reconnecting client receives
                            # either the live opening or this persisted replay.
                            pending_time = await time_advance_service.get_pending(
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
                            active_plan = await action_plan_turn_application.active_for_room(
                                room_id
                            )
                            if active_plan is not None and active_plan.player_id == bound_player_id:
                                if (
                                    active_plan.status == "awaiting_time_consent"
                                    and not isinstance(
                                        pending_time,
                                        TimeAdvancePendingPayload,
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
                                # No ActionPlan-driven pending decision — but a
                                # standalone single-action check (not part of a
                                # plan) has no room/player-scoped record the
                                # client can rediscover on its own after a
                                # refresh drops its local pendingAdjudication
                                # state; look one up explicitly so reconnect
                                # resurfaces it exactly like the plan case above.
                                action_request_id = (
                                    await adjudication_engine_service.find_active_action_for_player(
                                        room_id=room_id,
                                        player_id=bound_player_id,
                                    )
                                )
                                if action_request_id is not None:
                                    replayed = await _recover_persisted_turn_narration(
                                        db,
                                        websocket,
                                        room_id=room_id,
                                        player_id=bound_player_id,
                                        client_action_id=action_request_id,
                                    )
                                    if replayed:
                                        await time_advance_service.mark_narration_persisted(
                                            db,
                                            room_id=room_id,
                                            parent_action_id=action_request_id,
                                        )
                                    else:
                                        recovered = (
                                            await action_plan_turn_application.resume_single(
                                                room_id=room_id,
                                                player_id=bound_player_id,
                                                parent_action_id=action_request_id,
                                            )
                                        )
                                        await _send_action_plan_result(
                                            db,
                                            websocket,
                                            room_id,
                                            bound_player_id,
                                            recovered,
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
                        await _send_view_updated(
                            websocket,
                            bound_player_id,
                            initial_view,
                        )
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
                    elif event_type == "time.advance.respond":
                        response_payload = TimeAdvanceRespondPayload.model_validate(raw_payload)
                        try:
                            result, resume_player_id, action_request_id = (
                                await time_advance_service.respond(
                                    db,
                                    engine=adjudication_engine_service,
                                    room_id=room_id,
                                    player_id=bound_player_id,
                                    proposal_id=response_payload.proposal_id,
                                    proposal_version=response_payload.proposal_version,
                                    source_revision=response_payload.source_revision,
                                    accept=response_payload.accept,
                                )
                            )
                        except time_advance_service.TimeAdvanceError as exc:
                            await _send_error(websocket, "TIME_ADVANCE_CONFLICT", str(exc))
                            continue
                        await _broadcast_time_advance(room_id, result)
                        if resume_player_id is not None and action_request_id is not None:
                            resumed = await action_plan_turn_application.resume_pending(
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
                    elif event_type == "action.plan.submit":
                        submit_payload = ActionSubmitPayload.model_validate(raw_payload)
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
                        lock_token = action_lock_manager.try_acquire(room_id)
                        if lock_token is None:
                            await _send_error(
                                websocket,
                                "ACTION_IN_PROGRESS",
                                "守秘人正在处理其他玩家的行动，请稍候",
                                correlation_id=submit_payload.client_action_id,
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
                                await _send_error(
                                    websocket,
                                    "ACTION_IN_PROGRESS",
                                    "守秘人正在处理其他玩家的行动计划，请稍候",
                                    correlation_id=submit_payload.client_action_id,
                                )
                                continue
                            await _send_turn_event(
                                websocket,
                                TurnStarted(correlation_id=submit_payload.client_action_id),
                            )
                            result = await action_plan_turn_application.start(
                                room_id=room_id,
                                player_id=bound_player_id,
                                client_action_id=submit_payload.client_action_id,
                                utterance=submit_payload.utterance,
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
                            action_lock_manager.release(room_id, lock_token)
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
                            execution = await adjudication_engine_service.decide(
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
                            result = await action_plan_turn_application.resume_pending(
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
                    elif event_type == "adjudication.post_roll":
                        choice = AdjudicationPostRollPayload.model_validate(raw_payload)
                        try:
                            execution = await adjudication_engine_service.decide_post_roll(
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
                            result = await action_plan_turn_application.resume_pending(
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
                    elif event_type == "action.plan.cancel":
                        cancel = ActionPlanCancelPayload.model_validate(raw_payload)
                        try:
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
