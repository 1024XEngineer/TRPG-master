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
    manager.add(room_id, websocket)
    await websocket.send_json(
        {"type": "session.bound", "payload": {"roomId": room_id, "playerId": player_id}}
    )
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
            envelope = await websocket.receive_json()
            event_type = envelope.get("type")
            player_id = envelope.get("playerId")
            payload = envelope.get("payload") or {}

            if event_type == "room.join":
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
                await room_service.set_player_ready(bound_player_id, bool(payload.get("ready")))
            elif event_type == "game.start":
                try:
                    await room_service.begin_game(room_id, bound_player_id)
                except (
                    room_service.RoomNotFoundError,
                    room_service.RoomAuthorizationError,
                    room_service.RoomConflictError,
                ):
                    continue
                await manager.broadcast(
                    room_id, {"type": "narration.push", "payload": {"text": _OPENING_NARRATION}}
                )
            elif event_type == "action.submit":
                utterance = str(payload.get("utterance", "")).strip()
                if not utterance:
                    continue
                await manager.broadcast(
                    room_id,
                    {
                        "type": "narration.push",
                        "payload": {"text": f"守秘人记下了你的行动：「{utterance}」……"},
                    },
                )
    except WebSocketDisconnect:
        pass
    finally:
        manager.remove(room_id, websocket)
