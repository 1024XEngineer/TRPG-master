"""房间级 WebSocket 连接登记表（issue #60）。

只负责"这个房间当前有哪些连接、往它们广播一条消息"，不关心业务逻辑——
业务状态（玩家列表/准备/建卡完成/房间阶段）仍然是 service/room.py 里的
内存 stub，WS 层只是在事件发生时读写它、再把结果广播出去。
"""

import contextlib

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}

    def add(self, room_id: str, websocket: WebSocket) -> None:
        self._rooms.setdefault(room_id, set()).add(websocket)

    def remove(self, room_id: str, websocket: WebSocket) -> None:
        connections = self._rooms.get(room_id)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            del self._rooms[room_id]

    async def broadcast(self, room_id: str, message: dict) -> None:
        # 复制一份快照再遍历：广播过程中某个连接掉线触发 remove() 会改动
        # 原集合，直接遍历原集合会撞上"运行时改变集合大小"的异常。
        for websocket in list(self._rooms.get(room_id, ())):
            # 发送失败（连接已经断了但还没走到 disconnect 清理）忽略，
            # 交给该连接自己的 receive 循环去 remove()。
            with contextlib.suppress(Exception):
                await websocket.send_json(message)


manager = ConnectionManager()
