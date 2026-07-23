"""顶层 `/ws/{roomId}` WebSocket 路由（issue #60，issue #77 补齐 14 个新事件 +
切换为真实 ORM 读写）。

故意不挂在 `/api/v1` 前缀下——前端约定的连接地址是
`ws://host/ws/{roomId}?token={token}`，是独立于 REST API 版本号的实时通道，
`roomId` 是房间内部 ID（不是玩家分享用的 roomCode）。

协议（跟 trpg-app 原型 services/api-client.ts 对齐）：
- 客户端发送 `{type, playerId, payload}`；
- 服务端推送 `{type, payload}`；
- 连接后第一条消息必须是 `room.join`，成功后回 `session.bound`，
  在此之前收到的其它事件类型会被忽略（还没确认这个连接对应哪个玩家）；
- `player.ready`/`game.start`/`action.submit` 读写 `players`/`rooms` 表，
  玩家列表/准备/建卡完成/阶段仍然靠前端轮询 `GET /rooms/{roomCode}` 获取
  （issue #77"三处原型取舍"表格，`room.state`/`player.joined` 协议槽位已经
  留好，但本期不会真的发出）。
- `action.submit` 的叙事回复本期是固定文案的占位实现（"Mock 叙事"，
  issue #43 允许），真实 AI 叙事生成留给 #43 落地。
- `check.roll`/`san.check.roll`/`room.rejoin` 三个新增 C→S 事件校验完
  payload 后统一回一条 `error` 事件（`NOT_IMPLEMENTED`），不做真实的服务端
  权威掷骰/断线重连（issue #77"三处原型取舍"表格 + 决策 6）。
- 每条广播出去的 `narration.push` 都会同步写一行 `events` 表——这是本期
  唯一真正打通的事件日志闭环，`GET /rooms/{roomId}/replay` 直接读它。

数据库会话按"每条消息一个短 session"处理，而不是整条连接复用一个：一个
WebSocket 可能存活很久，用一个 session 包住整条连接会在这期间一直占着一个
数据库连接/事务，跟并发的 HTTP 请求争抢 SQLite 的锁（测试里表现为死锁）。
鉴权单独用一个短 session，之后每条消息各开各的，消息之间等待时不持有连接。
"""

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory
from app.dto.ws import (
    ActionBroadcastPayload,
    ActionSubmitPayload,
    ChatMessagePayload,
    ChatSendPayload,
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
from app.service import chat as chat_service
from app.service import room as room_service
from app.service.action_lock import action_lock_manager
from app.service.ws_manager import manager

router = APIRouter()
logger = structlog.get_logger()

_UNAUTHORIZED_CLOSE_CODE = 4401
_NOT_FOUND_CLOSE_CODE = 4404
_OPENING_NARRATION = "案件已加载。守秘人整理好了开场的场景描述，故事即将开始……"


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    """只发给触发这次交互的那一个连接，不广播——`error` 事件是"告诉发起者
    这次请求怎么了"，不是房间广播内容（issue #77 新增）。"""
    payload = ErrorPayload(code=code, message=message)
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
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))
    await room_service.record_event(db, room_id, player_id, "narration.push", {"text": text})


async def _handle_room_join(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str | None,
    reconnect_token: str,
) -> bool:
    """处理 room.join：校验 playerId 属于这个房间、且出示了该玩家的
    reconnect_token（证明是本人，不是拿别人 playerId 冒充），成功后登记连接并回
    session.bound。返回是否绑定成功。
    """
    player = await room_service.get_player(db, player_id) if player_id else None
    if player is None or player.room_id != room_id or player.reconnect_token != reconnect_token:
        await websocket.close(code=_NOT_FOUND_CLOSE_CODE)
        return False
    assert player_id is not None  # 上面能走到这里，player_id 必然非空（见 get_player 调用）
    manager.add(room_id, websocket)
    await room_service.set_player_connected(db, player_id, True)
    payload = SessionBoundPayload(room_id=room_id, player_id=player_id)
    envelope = ServerEnvelope(type="session.bound", payload=payload.model_dump(by_alias=True))
    await websocket.send_json(envelope.model_dump(by_alias=True))
    return True


async def _handle_chat_send(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str,
    payload: ChatSendPayload,
) -> None:
    """处理 chat.send：落库（重发幂等）后把 chat.message 广播给全房间。

    讨论区消息**不写 events 表、不进任何 LLM 上下文**——它跟 action.submit
    是两条独立通道（两个界面），这是 issue #107 的立项设计。
    """
    text = payload.text.strip()
    if not text:
        return
    player = await room_service.get_player(db, player_id)
    if player is None or player.room_id != room_id:
        return
    # 游戏结束后禁止写入讨论消息——否则 /end 清理后仍存活的 WS 可以重新落库，
    # 导致清理失效且无法再次调用 /end 清除。
    try:
        room = await room_service.find_room_by_id(db, room_id)
        if room.phase == "Completed":
            await _send_error(websocket, "FORBIDDEN", "游戏已结束，无法发送消息")
            return
    except room_service.RoomNotFoundError:
        return
    message = await chat_service.save_chat_message(
        db, room_id, player_id, text, payload.client_message_id
    )
    chat_message = ChatMessagePayload(
        message_id=message.id,
        player_id=message.player_id,
        nickname=player.nickname,
        text=message.text,
        sent_at=message.created_at,
        client_message_id=message.client_message_id,
    )
    envelope = ServerEnvelope(
        type="chat.message", payload=chat_message.model_dump(by_alias=True, mode="json")
    )
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))


async def _handle_action_submit(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str,
    utterance: str,
) -> None:
    """处理 action.submit：玩家对 AI 主持人说的任何一句话（issue #107 定稿后
    的唯一事件——"是行动还是提问"由 AI 判断，协议层不预分类）。

    流程：拿房间锁 → 广播玩家原话（action.broadcast）→ 调 Narrator 生成
    叙事 → 广播回复（narration.push）→ 释放锁。

    - 锁：同一房间同一时刻只允许一个「读状态→跑 AI→写回」循环，其他人的
      提交直接拒（ACTION_IN_PROGRESS），防止两次并发生成读到同一份旧状态、
      产出矛盾叙事。finally 无条件释放 + 锁自身的超时兜底（action_lock.py），
      保证一次 AI 失败不会永久锁死房间。
    - 玩家原话广播：修"聊天记录像被隔离"的 bug——此前原话只在发送方本地
      插入，其他人只能看到守秘人转述。
    - Narrator 失败（超时/网络/API 错）：只告诉发起者（error 不广播），
      其他人看到了原话但等不到回复，发起者重试即可。
    """
    lock_token = action_lock_manager.try_acquire(room_id)
    if lock_token is None:
        await _send_error(websocket, "ACTION_IN_PROGRESS", "守秘人正在处理其他玩家的行动，请稍候")
        return

    try:
        player = await room_service.get_player(db, player_id)
        nickname = player.nickname if player is not None else "玩家"

        # ⚠️ 先组叙事上下文、后写事件：build_narration_context 靠"当前这条
        # 还没入库"来保证历史里不含它（见该函数 docstring 的时序约定）。
        context = await room_service.build_narration_context(db, room_id, player_id, utterance)
        await room_service.record_event(
            db, room_id, player_id, "action.submit", {"utterance": utterance}
        )

        broadcast_payload = ActionBroadcastPayload(
            player_id=player_id, nickname=nickname, utterance=utterance
        )
        envelope = ServerEnvelope(
            type="action.broadcast", payload=broadcast_payload.model_dump(by_alias=True)
        )
        await manager.broadcast(room_id, envelope.model_dump(by_alias=True))

        narrator = websocket.app.state.narrator
        try:
            narration_text = await narrator.narrate(context)
        except Exception as exc:  # 外部服务的失败面（网络/超时/API 错）就是宽的，故意宽捕获
            logger.warning("narrator_failed", room_id=room_id, error=str(exc))
            await _send_error(websocket, "INTERNAL_ERROR", "守秘人暂时无法回应，请稍后重试")
            return
        await _broadcast_narration(db, room_id, player_id, narration_text)
    finally:
        action_lock_manager.release(room_id, lock_token)


@router.websocket("/ws/{room_id}")
async def room_socket(websocket: WebSocket, room_id: str, token: str | None = None) -> None:
    # 鉴权只用一个短 session，用完立刻释放。**不要用一个 session 包住整条连接
    # 的生命周期**——那样会在整个 WebSocket 存续期间一直占着一个数据库连接/
    # 事务，跟并发的 HTTP 请求争抢 SQLite 的锁（在测试里表现为 HTTP 请求、或者
    # 用例结束时的建表/删表拿不到连接而死锁）。下面每条消息各开各的短 session。
    async with async_session_factory() as db:
        try:
            await auth_service.get_me(db, token)
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
                            db, websocket, room_id, player_id, join_payload.reconnect_token
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
                    elif event_type == "action.submit":
                        submit_payload = ActionSubmitPayload.model_validate(raw_payload)
                        utterance = submit_payload.utterance.strip()
                        if not utterance:
                            continue
                        # visibility="private"（私密行动，结果只给发起者）本期只铺
                        # 协议位——真正的私密裁决要 AI 知道"这条不能在后续叙事里
                        # 泄露"，属于编排层（issue #107）。明确回 NOT_IMPLEMENTED，
                        # 绝不静默当 public 处理——否则玩家以为保密的行动被广播出去，
                        # 当场暴露。
                        if submit_payload.visibility == "private":
                            await _send_error(websocket, "NOT_IMPLEMENTED", "私密行动本期尚未实现")
                            continue
                        await _handle_action_submit(
                            db, websocket, room_id, bound_player_id, utterance
                        )
                    elif event_type == "chat.send":
                        chat_payload = ChatSendPayload.model_validate(raw_payload)
                        await _handle_chat_send(
                            db, websocket, room_id, bound_player_id, chat_payload
                        )
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
    finally:
        manager.remove(room_id, websocket)
        # 断线清理另开一个短 session：上面每条消息用的 db 作用域已经结束，
        # 这里要把玩家标记为已断开，需要一个新的会话。
        if bound_player_id is not None:
            async with async_session_factory() as db:
                await room_service.set_player_connected(db, bound_player_id, False)
