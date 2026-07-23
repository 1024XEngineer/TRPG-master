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
- `check.roll`/`san.check.roll`/`room.rejoin` 三个新增 C→S 事件校验完
  payload 后统一回一条 `error` 事件（`NOT_IMPLEMENTED`），不做真实的服务端
  权威掷骰/断线重连（issue #77"三处原型取舍"表格 + 决策 6）。
- 每条实际发送的 `narration.push` 都会同步写一行 `events` 表；动作叙事用
  `clientActionId` 做持久化去重，`GET /rooms/{roomId}/replay` 直接读它。

数据库会话按"每条消息一个短 session"处理，而不是整条连接复用一个：一个
WebSocket 可能存活很久，用一个 session 包住整条连接会在这期间一直占着一个
数据库连接/事务，跟并发的 HTTP 请求争抢 SQLite 的锁（测试里表现为死锁）。
鉴权单独用一个短 session，之后每条消息各开各的，消息之间等待时不持有连接。
"""

import structlog
from collaboration_framework.contracts import ContractError
from collaboration_framework.engine import RevisionConflictError
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.websockets import WebSocketState

from app.core.db import async_session_factory
from app.core.turn import ActorResolutionError, turn_application
from app.dto.ws import (
    ActionSubmitPayload,
    CheckRollPayload,
    ClientEnvelope,
    ErrorPayload,
    GameStartPayload,
    NarrationPushPayload,
    PlayerReadyPayload,
    RoomJoinPayload,
    RoomRejoinPayload,
    SanCheckRollPayload,
    ServerEnvelope,
    SessionBoundPayload,
)
from app.service import auth as auth_service
from app.service import room as room_service
from app.service.ws_events import broadcast_room_state
from app.service.ws_manager import manager

router = APIRouter()
logger = structlog.get_logger()

_UNAUTHORIZED_CLOSE_CODE = 4401
_NOT_FOUND_CLOSE_CODE = 4404
_OPENING_NARRATION = "案件已加载。守秘人整理好了开场的场景描述，故事即将开始……"


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


async def _broadcast_narration(
    db: AsyncSession, room_id: str, player_id: str | None, text: str
) -> None:
    """广播一条 narration.push，并同步写一行 `events` 表——`GET
    /rooms/{roomId}/replay` 读的就是这里写入的数据（issue #77 才打通的
    EventLog 闭环，此前"不记 EventLog"是已知缺口）。
    """
    narration = NarrationPushPayload(text=text)
    envelope = ServerEnvelope(type="narration.push", payload=narration.model_dump(by_alias=True))
    await room_service.record_event(db, room_id, player_id, "narration.push", {"text": text})
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))


async def _deliver_turn_narration(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str,
    *,
    client_action_id: str,
    text: str,
    clarification: bool,
) -> None:
    """持久化去重成功后才发送一次动作叙事。"""

    recorded = await room_service.record_event(
        db,
        room_id,
        player_id,
        "narration.push",
        {"text": text},
        correlation_id=client_action_id,
    )
    if not recorded:
        return
    narration = NarrationPushPayload(text=text)
    envelope = ServerEnvelope(type="narration.push", payload=narration.model_dump(by_alias=True))
    message = envelope.model_dump(by_alias=True)
    if clarification:
        await websocket.send_json(message)
    else:
        await manager.broadcast(room_id, message)


def _map_turn_error(exc: Exception) -> tuple[str, str]:
    if isinstance(exc, ActorResolutionError):
        return "ACTOR_NOT_CONTROLLED", "当前玩家没有可控制的局内角色"
    if isinstance(exc, RevisionConflictError):
        return "REVISION_CONFLICT", "房间状态已被其他动作更新，请重试"
    if isinstance(exc, SQLAlchemyError):
        return "DATABASE_CONFLICT", "动作提交发生数据库并发冲突，请重试"

    message = str(exc)
    if "运行时不存在" in message:
        return "ROOM_RUNTIME_NOT_FOUND", "房间尚未建立可用的游戏运行时"
    if "不是可提交动作的 InGame" in message:
        return "ROOM_NOT_ACTIONABLE", "房间当前状态不允许提交动作"
    if "request_id 已用于不同" in message:
        return "ACTION_ID_CONFLICT", "clientActionId 已被另一动作占用"
    if "过期 PlayerView" in message:
        return "SOURCE_REVISION_STALE", "动作基于过期的玩家视图，请重试"
    if "player_id/actor_id" in message:
        return "ACTOR_NOT_CONTROLLED", "当前玩家不能控制该局内角色"
    if isinstance(exc, (ContractError, ValidationError)):
        return "TURN_CONTRACT_INVALID", "本次动作未通过主持编排契约校验"
    return "TURN_INTERNAL_ERROR", "本次动作处理失败，请稍后重试"


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
    async with async_session_factory() as db:
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
                logger.warning("ws_invalid_message", event_type=bad_type, error=str(exc))
                continue

            event_type = client_envelope.type
            player_id = client_envelope.player_id
            raw_payload = client_envelope.payload

            # 每条消息各开一个短 session，处理完立刻释放——WebSocket 在两条消息
            # 之间等待（receive_json 阻塞）时不持有任何数据库连接。
            async with async_session_factory() as db:
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
                        await _broadcast_narration(db, room_id, bound_player_id, _OPENING_NARRATION)
                        await broadcast_room_state(db, room_id)
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
                                error=str(exc),
                            )
                            await _send_error(
                                websocket,
                                "INVALID_ACTION",
                                "action.submit 必须包含非空 clientActionId 和 utterance",
                                correlation_id=correlation_id,
                            )
                            continue
                        try:
                            output = await turn_application.handle(
                                room_id=room_id,
                                player_id=bound_player_id,
                                client_action_id=submit_payload.client_action_id,
                                utterance=submit_payload.utterance,
                            )
                            await websocket.send_json(output.to_json_dict())
                            await _deliver_turn_narration(
                                db,
                                websocket,
                                room_id,
                                bound_player_id,
                                client_action_id=submit_payload.client_action_id,
                                text=output.payload.narration.text,
                                clarification=output.payload.narration.kind == "clarification",
                            )
                            if output.payload.player_view.phase == "ended":
                                await broadcast_room_state(db, room_id)
                        except Exception as exc:
                            code, message = _map_turn_error(exc)
                            logger.warning(
                                "ws_turn_failed",
                                code=code,
                                correlation_id=submit_payload.client_action_id,
                                error=str(exc),
                            )
                            await _send_error(
                                websocket,
                                code,
                                message,
                                correlation_id=submit_payload.client_action_id,
                            )
                            continue
                    elif event_type == "check.roll":
                        CheckRollPayload.model_validate(raw_payload)
                        await _send_error(
                            websocket, "NOT_IMPLEMENTED", "服务端权威技能检定本期尚未实现"
                        )
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
                    logger.warning("ws_invalid_message", event_type=event_type, error=str(exc))
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
            async with async_session_factory() as db:
                await room_service.set_player_connected(db, bound_player_id, False)
