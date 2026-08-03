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
- `player.ready`/`game.start`/`action.submit` 使用服务端权威状态，并在房间
  阶段或玩家状态变化后广播 `room.state`；
- `action.submit` 必须携带 `clientActionId`，由 TurnApplication 完成身份绑定、
  编排、幂等去重和 PlayerView 投影；框架回包只发给动作发起者，普通叙事广播
  全房间，需要澄清的叙事只发给发起者；
- `action.submit` 需要检定时先回 `check.request`；玩家用 `check.roll`
  选择技能并提交 D100 点数后，引擎才结算状态、返回 `check.result` 和叙述。
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

import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import partial

import anyio
import structlog
from collaboration_framework.contracts import (
    ActionResult,
    ContractError,
    PlayerInput,
    PlayerView,
)
from collaboration_framework.engine import RevisionConflictError
from collaboration_framework.host.application import (
    TurnExecutionError,
    normalize_narration_text,
    split_narration_chunks,
)
from collaboration_framework.host.schemas import TurnOutput
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from app.core.db import async_session_factory
from app.core.turn import ActorResolutionError, PreparedTurn, turn_application
from app.core.turn_events import (
    TurnEvent,
    TurnFailed,
    TurnPhaseChanged,
    TurnStarted,
    TurnToolCompleted,
    TurnToolStarted,
)
from app.core.turn_observability import (
    log_check_result,
    log_narration_output,
    log_player_input,
    log_turn_completed,
    log_turn_failed,
)
from app.dto.ws import (
    ActionBroadcastPayload,
    ActionSubmitPayload,
    ChatMessagePayload,
    ChatSendPayload,
    CheckRequestPayload,
    CheckResultPayload,
    CheckRollPayload,
    CheckSkillOptionPayload,
    ClientEnvelope,
    ErrorPayload,
    GameStartPayload,
    NarrationChunkPayload,
    NarrationPushPayload,
    OpeningStartedPayload,
    PlayerReadyPayload,
    RoomJoinPayload,
    RoomRejoinPayload,
    SanCheckRollPayload,
    ServerEnvelope,
    SessionBoundPayload,
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
from app.service.action_lock import action_lock_manager
from app.service.ws_events import broadcast_room_state
from app.service.ws_manager import manager

router = APIRouter()
logger = structlog.get_logger()

_UNAUTHORIZED_CLOSE_CODE = 4401
_NOT_FOUND_CLOSE_CODE = 4404
_OPENING_MESSAGE_ID = "game-opening"


@asynccontextmanager
async def _short_db_session() -> AsyncIterator[AsyncSession]:
    """Always finish SQLAlchemy cleanup even when a WebSocket task is cancelled."""

    session = async_session_factory()
    try:
        yield session
    finally:
        with anyio.CancelScope(shield=True):
            await session.close()


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
    await websocket.send_json(envelope.model_dump(by_alias=True))


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
    await websocket.send_json(envelope.model_dump(by_alias=True))


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
    await websocket.send_json(envelope.model_dump(by_alias=True))


async def _stream_narration_chunks(
    send: Callable[[dict], Awaitable[None]],
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
    await websocket.send_json(envelope.model_dump(by_alias=True))
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

    if turn_application.opening_narration_mode == "model":
        started = OpeningStartedPayload(message_id=_OPENING_MESSAGE_ID)
        await manager.broadcast(
            room_id,
            ServerEnvelope(
                type="opening.started",
                payload=started.model_dump(by_alias=True),
            ).model_dump(by_alias=True),
        )

    generated = await turn_application.generate_opening(player_view)
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
    text: str,
    clarification: bool,
    actor_id: str,
    scene_id: str,
    view_revision: str,
) -> bool:
    """持久化去重成功后才发送一次动作叙事。"""

    text = normalize_narration_text(text)
    narration = NarrationPushPayload(
        message_id=client_action_id,
        text=text,
    )
    payload = narration.model_dump(by_alias=True)
    recorded = await room_service.record_event(
        db,
        room_id,
        player_id,
        "narration.push",
        payload,
        visibility="player_scoped" if clarification else "public",
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
        clarification=clarification,
    )
    # 澄清叙事只对发起者可见，它的渐进片段必须走同一条投递通道，
    # 否则片段会广播给全房间、泄露只该给一个人看的内容。
    send = websocket.send_json if clarification else partial(manager.broadcast, room_id)
    await _stream_narration_chunks(
        send,
        message_id=client_action_id,
        text=text,
    )
    envelope = ServerEnvelope(type="narration.push", payload=payload)
    await send(envelope.model_dump(by_alias=True))
    return True


async def _send_check_request(
    websocket: WebSocket,
    player_id: str,
    prepared: PreparedTurn,
) -> None:
    payload = CheckRequestPayload(
        player_id=player_id,
        client_action_id=prepared.player_input.client_action_id,
        summary=prepared.intent.summary,
        difficulty=prepared.difficulty,
        skills=[
            CheckSkillOptionPayload(
                id=candidate.id,
                name=candidate.name,
                target_value=candidate.target_value,
            )
            for candidate in prepared.candidates
        ],
    )
    envelope = ServerEnvelope(
        type="check.request",
        payload=payload.model_dump(by_alias=True),
    )
    await websocket.send_json(envelope.model_dump(by_alias=True))


async def _send_check_result(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str,
    prepared: PreparedTurn,
    action_result: ActionResult,
    player_view: PlayerView,
) -> None:
    check_result = action_result.check_result
    if check_result is None:
        raise ContractError("Completed skill check did not return a check result")
    candidate = next(item for item in prepared.candidates if item.id == check_result.skill_id)
    character_name = await room_service.get_player_character_name(db, player_id)
    payload = CheckResultPayload(
        player_id=player_id,
        client_action_id=prepared.player_input.client_action_id,
        skill=check_result.skill_id,
        skill_name=candidate.name,
        character_name=character_name,
        roll_value=check_result.roll_value,
        target_value=check_result.target_value,
        difficulty=check_result.difficulty,
        success_level=check_result.success_level,
        passed=check_result.passed,
        result=check_result.success_level,
    )
    recorded = await room_service.record_event(
        db,
        room_id,
        player_id,
        "check.result",
        payload.model_dump(by_alias=True, mode="json"),
        visibility="player_scoped",
        actor_id=prepared.player_input.actor_id,
        scene_id=player_view.scene_id,
        view_revision=player_view.revision,
        correlation_id=prepared.player_input.client_action_id,
    )
    if not recorded:
        return
    log_check_result(
        room_id=room_id,
        correlation_id=prepared.player_input.client_action_id,
        character_name=character_name,
        skill_name=candidate.name,
        target_value=check_result.target_value,
        roll_value=check_result.roll_value,
        difficulty=check_result.difficulty,
        success_level=check_result.success_level,
        passed=check_result.passed,
    )
    envelope = ServerEnvelope(
        type="check.result",
        payload=payload.model_dump(by_alias=True),
    )
    await websocket.send_json(envelope.model_dump(by_alias=True))


async def _send_completed_turn(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str,
    output: TurnOutput,
) -> bool:
    websocket_output = output.to_websocket_output()
    await websocket.send_json(websocket_output.to_json_dict())
    await _send_view_updated(websocket, player_id, output.player_view)
    narration_sent = await _deliver_turn_narration(
        db,
        websocket,
        room_id,
        player_id,
        client_action_id=output.player_input.client_action_id,
        text=output.narration.text,
        clarification=output.narration.kind == "clarification",
        actor_id=output.player_input.actor_id,
        scene_id=output.player_view.scene_id,
        view_revision=output.player_view.revision,
    )
    if output.player_view.phase == "ended":
        await broadcast_room_state(db, room_id)
    return narration_sent


def _map_turn_error(exc: Exception) -> tuple[str, str, bool]:
    if isinstance(exc, TurnExecutionError):
        return exc.code, exc.public_message, exc.retryable
    if isinstance(exc, ActorResolutionError):
        return "ACTOR_NOT_CONTROLLED", "当前玩家没有可控制的局内角色", False
    if isinstance(exc, RevisionConflictError):
        return "REVISION_CONFLICT", "房间状态已被其他动作更新，请重试", True
    if isinstance(exc, SQLAlchemyError):
        return "DATABASE_CONFLICT", "动作提交发生数据库并发冲突，请重试", True

    message = str(exc)
    if "运行时不存在" in message:
        return "ROOM_RUNTIME_NOT_FOUND", "房间尚未建立可用的游戏运行时", True
    if "不是可提交动作的 InGame" in message:
        return "ROOM_NOT_ACTIONABLE", "房间当前状态不允许提交动作", False
    if "request_id 已用于不同" in message:
        return "ACTION_ID_CONFLICT", "clientActionId 已被另一动作占用", False
    if "过期 PlayerView" in message:
        return "SOURCE_REVISION_STALE", "动作基于过期的玩家视图，请重试", True
    if "player_id/actor_id" in message:
        return "ACTOR_NOT_CONTROLLED", "当前玩家不能控制该局内角色", False
    if isinstance(exc, (ContractError, ValidationError)):
        return "TURN_CONTRACT_INVALID", "本次动作未通过主持编排契约校验", False
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
    manager.add(room_id, websocket)
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
    pending_turn: PreparedTurn | None = None

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
                                current_view = await turn_application.current_player_view(
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
                            await _send_persisted_opening(db, websocket, room_id)
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
                        initial_view = await turn_application.current_player_view(
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
                    elif event_type == "action.submit":
                        try:
                            submit_payload = ActionSubmitPayload.model_validate(raw_payload)
                        except ValidationError as exc:
                            correlation_id = (
                                raw_payload.get("clientActionId")
                                if isinstance(raw_payload.get("clientActionId"), str)
                                else None
                            )
                            logger.warning(
                                "ws_invalid_action",
                                correlation_id=correlation_id,
                                validation_error_count=exc.error_count(),
                            )
                            await _send_error(
                                websocket,
                                "INVALID_ACTION",
                                "action.submit 必须包含非空 clientActionId 和 utterance",
                                correlation_id=correlation_id,
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
                        lock_token = action_lock_manager.try_acquire(room_id)
                        if lock_token is None:
                            await _send_error(
                                websocket,
                                "ACTION_IN_PROGRESS",
                                "守秘人正在处理其他玩家的行动，请稍候",
                                correlation_id=submit_payload.client_action_id,
                            )
                            continue
                        turn_started_at = time.monotonic()
                        try:
                            if pending_turn is not None:
                                same_action = (
                                    pending_turn.player_input.client_action_id
                                    == submit_payload.client_action_id
                                    and pending_turn.player_input.utterance
                                    == submit_payload.utterance
                                )
                                if same_action:
                                    await _send_check_request(
                                        websocket,
                                        bound_player_id,
                                        pending_turn,
                                    )
                                else:
                                    await _send_error(
                                        websocket,
                                        "CHECK_PENDING",
                                        "请先完成当前待处理的技能检定",
                                        correlation_id=submit_payload.client_action_id,
                                    )
                                continue

                            prepared = await turn_application.prepare(
                                room_id=room_id,
                                player_id=bound_player_id,
                                client_action_id=submit_payload.client_action_id,
                                utterance=submit_payload.utterance,
                                on_event=lambda event: _send_turn_event(
                                    websocket,
                                    event,
                                ),
                                on_input_accepted=partial(
                                    _broadcast_action_utterance,
                                    db,
                                ),
                            )
                            if prepared.candidates:
                                pending_turn = prepared
                                await _send_check_request(
                                    websocket,
                                    bound_player_id,
                                    prepared,
                                )
                                continue

                            output = await turn_application.complete(
                                prepared,
                                on_event=lambda event: _send_turn_event(
                                    websocket,
                                    event,
                                ),
                            )
                            narration_sent = await _send_completed_turn(
                                db,
                                websocket,
                                room_id,
                                bound_player_id,
                                output,
                            )
                            log_turn_completed(
                                room_id=room_id,
                                correlation_id=output.player_input.client_action_id,
                                intent_summary=output.intent.summary,
                                resolution=output.action_result.resolution,
                                outcome=output.action_result.outcome,
                                revision=output.action_result.view_revision,
                                duration_ms=int((time.monotonic() - turn_started_at) * 1000),
                                narration_sent=narration_sent,
                            )
                        except Exception as exc:
                            code, _, _ = _map_turn_error(exc)
                            log_turn_failed(
                                room_id=room_id,
                                stage="行动处理",
                                code=code,
                                correlation_id=submit_payload.client_action_id,
                                error_type=type(exc).__name__,
                                error_reason=_turn_error_reason(exc),
                            )
                            await _send_turn_failed(
                                websocket,
                                submit_payload.client_action_id,
                                exc,
                            )
                            continue
                        finally:
                            action_lock_manager.release(room_id, lock_token)
                    elif event_type == "check.roll":
                        roll_payload = CheckRollPayload.model_validate(raw_payload)
                        if pending_turn is None:
                            await _send_error(
                                websocket,
                                "CHECK_NOT_PENDING",
                                "当前没有等待投掷的技能检定",
                                correlation_id=roll_payload.client_action_id,
                            )
                            continue
                        if (
                            pending_turn.player_input.client_action_id
                            != roll_payload.client_action_id
                        ):
                            await _send_error(
                                websocket,
                                "CHECK_ACTION_MISMATCH",
                                "检定结果与当前待处理动作不匹配",
                                correlation_id=roll_payload.client_action_id,
                            )
                            continue
                        lock_token = action_lock_manager.try_acquire(room_id)
                        if lock_token is None:
                            await _send_error(
                                websocket,
                                "ACTION_IN_PROGRESS",
                                "守秘人正在处理其他玩家的行动，请稍候",
                                correlation_id=roll_payload.client_action_id,
                            )
                            continue
                        turn_started_at = time.monotonic()
                        try:
                            output = await turn_application.complete(
                                pending_turn,
                                selected_skill=roll_payload.skill,
                                roll_value=roll_payload.roll_value,
                                on_event=lambda event: _send_turn_event(
                                    websocket,
                                    event,
                                ),
                                on_action_result=partial(
                                    _send_check_result,
                                    db,
                                    websocket,
                                    room_id,
                                    bound_player_id,
                                    pending_turn,
                                ),
                            )
                            pending_turn = None
                            narration_sent = await _send_completed_turn(
                                db,
                                websocket,
                                room_id,
                                bound_player_id,
                                output,
                            )
                            log_turn_completed(
                                room_id=room_id,
                                correlation_id=output.player_input.client_action_id,
                                intent_summary=output.intent.summary,
                                resolution=output.action_result.resolution,
                                outcome=output.action_result.outcome,
                                revision=output.action_result.view_revision,
                                duration_ms=int((time.monotonic() - turn_started_at) * 1000),
                                narration_sent=narration_sent,
                            )
                        except Exception as exc:
                            code, _, retryable = _map_turn_error(exc)
                            if code in {"NARRATOR_FAILED", "NARRATION_INVALID"} or not retryable:
                                pending_turn = None
                            log_turn_failed(
                                room_id=room_id,
                                stage="检定结算",
                                code=code,
                                correlation_id=roll_payload.client_action_id,
                                error_type=type(exc).__name__,
                                error_reason=_turn_error_reason(exc),
                            )
                            await _send_turn_failed(
                                websocket,
                                roll_payload.client_action_id,
                                exc,
                            )
                            continue
                        finally:
                            action_lock_manager.release(room_id, lock_token)
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
    except RuntimeError:
        # 广播可能先发现对端断开，使 send_json 把 application_state 标为
        # DISCONNECTED；随后当前连接的 receive_json 会抛 RuntimeError。
        # TestClient 的常规断连则通常直接抛 WebSocketDisconnect。
        if websocket.application_state is not WebSocketState.DISCONNECTED:
            raise
    finally:
        manager.remove(room_id, websocket)
        # 断线清理另开一个短 session：上面每条消息用的 db 作用域已经结束，
        # 这里要把玩家标记为已断开，需要一个新的会话。
        if bound_player_id is not None:
            with anyio.CancelScope(shield=True):
                async with _short_db_session() as db:
                    await room_service.set_player_connected(db, bound_player_id, False)
