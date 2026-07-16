"""顶层 `/ws/{roomId}` WebSocket 路由（issue #60）。

故意不挂在 `/api/v1` 前缀下——前端约定的连接地址是
`ws://host/ws/{roomId}?token={token}`，是独立于 REST API 版本号的实时通道，
`roomId` 是房间内部 ID（不是玩家分享用的 roomCode）。

协议（跟 trpg-app 原型 services/api-client.ts 对齐）：
- 客户端发送 `{type, playerId, payload}`；
- 服务端推送 `{type, payload}`；
- 连接后第一条消息必须是 `room.join`，成功后回 `session.bound`，
  在此之前收到的其它事件类型会被忽略（还没确认这个连接对应哪个玩家）；
- `player.ready`/`game.start`/`action.submit` 复用 service/room.py 的
  MS1 内存 stub 读写房间状态，玩家列表/准备/建卡完成/阶段仍然靠前端
  轮询 `GET /rooms/{roomCode}` 获取（issue #60"本期不做"里排除了这些的
  独立推送事件）。
- `action.submit` 的叙事回复本期是固定文案的占位实现（"Mock 叙事"，
  issue #43 允许），真实 AI 叙事生成留给 #43 落地。
"""

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from app.dto.ws import (
    ActionSubmitPayload,
    ClientEnvelope,
    GameStartPayload,
    NarrationPushPayload,
    PlayerReadyPayload,
    RoomJoinPayload,
    ServerEnvelope,
    SessionBoundPayload,
)
from app.service import auth as auth_service
from app.service import room as room_service
from app.service.ws_manager import manager

router = APIRouter()
logger = structlog.get_logger()

_UNAUTHORIZED_CLOSE_CODE = 4401
_NOT_FOUND_CLOSE_CODE = 4404
_OPENING_NARRATION = "案件已加载。守秘人整理好了开场的场景描述，故事即将开始……"


async def _handle_room_join(websocket: WebSocket, room_id: str, player_id: str | None) -> bool:
    """处理 room.join：校验 playerId 属于这个房间，成功后登记连接并回 session.bound。

    返回是否绑定成功。
    """
    player = room_service.get_player(player_id) if player_id else None
    if player is None or player["room_id"] != room_id:
        await websocket.close(code=_NOT_FOUND_CLOSE_CODE)
        return False
    assert player_id is not None  # 上面能走到这里，player_id 必然非空（见 get_player 调用）
    manager.add(room_id, websocket)
    payload = SessionBoundPayload(room_id=room_id, player_id=player_id)
    envelope = ServerEnvelope(type="session.bound", payload=payload.model_dump(by_alias=True))
    await websocket.send_json(envelope.model_dump(by_alias=True))
    return True


@router.websocket("/ws/{room_id}")
async def room_socket(websocket: WebSocket, room_id: str, token: str | None = None) -> None:
    try:
        await auth_service.get_me(token)
    except auth_service.AuthenticationError:
        await websocket.close(code=_UNAUTHORIZED_CLOSE_CODE)
        return

    await websocket.accept()
    bound_player_id: str | None = None

    try:
        while True:
            raw = await websocket.receive_json()

            # 每条消息的校验（信封 + payload）都包在这一层 try 里：一条格式
            # 不对的消息（比如整个信封都不是对象，或者 ready 传了个字符串
            # 而不是 bool）只应该丢弃这一条，不该让 ValidationError 冒出这个
            # 循环、打断整条 WS 连接——跟决策 5 里 SDK 端"校验不过就丢弃，
            # 不断连"的立场一致。
            try:
                client_envelope = ClientEnvelope.model_validate(raw)
                event_type = client_envelope.type
                player_id = client_envelope.player_id
                raw_payload = client_envelope.payload

                if event_type == "room.join":
                    RoomJoinPayload.model_validate(raw_payload)
                    if await _handle_room_join(websocket, room_id, player_id):
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
                    await room_service.set_player_ready(bound_player_id, ready_payload.ready)
                elif event_type == "game.start":
                    GameStartPayload.model_validate(raw_payload)
                    try:
                        await room_service.begin_game(room_id, bound_player_id)
                    except (
                        room_service.RoomNotFoundError,
                        room_service.RoomAuthorizationError,
                        room_service.RoomConflictError,
                    ):
                        continue
                    narration = NarrationPushPayload(text=_OPENING_NARRATION)
                    narration_envelope = ServerEnvelope(
                        type="narration.push", payload=narration.model_dump(by_alias=True)
                    )
                    await manager.broadcast(room_id, narration_envelope.model_dump(by_alias=True))
                elif event_type == "action.submit":
                    submit_payload = ActionSubmitPayload.model_validate(raw_payload)
                    utterance = submit_payload.utterance.strip()
                    if not utterance:
                        continue
                    narration = NarrationPushPayload(
                        text=f"守秘人记下了你的行动：「{utterance}」……"
                    )
                    narration_envelope = ServerEnvelope(
                        type="narration.push", payload=narration.model_dump(by_alias=True)
                    )
                    await manager.broadcast(room_id, narration_envelope.model_dump(by_alias=True))
            except ValidationError as exc:
                # 不用上面局部变量 event_type：如果连 ClientEnvelope 本身都
                # 没解析成功（比如 raw 整个不是对象、或者不是字典），
                # event_type 根本不会被赋值。raw 也不一定是字典（客户端可能
                # 发一个 JSON 数组/字符串上来），先判一下类型再取，避免这里
                # 自己又抛出一个未被捕获的 AttributeError。
                bad_type = raw.get("type") if isinstance(raw, dict) else None
                logger.warning("ws_invalid_message", event_type=bad_type, error=str(exc))
                continue
    except WebSocketDisconnect:
        pass
    finally:
        manager.remove(room_id, websocket)
