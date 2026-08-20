"""房间级 WebSocket 连接登记表（issue #60）。

只负责"这个房间当前有哪些连接、往它们广播一条消息"，不关心业务逻辑。
玩家列表、准备、建卡和房间阶段均由 service/room.py 通过数据库读写。
"""

import contextlib

from fastapi import WebSocket


class ConnectionManager:
    def __init__(self) -> None:
        self._rooms: dict[str, set[WebSocket]] = {}
        self._players: dict[tuple[str, str], set[WebSocket]] = {}
        self._identity_by_socket: dict[WebSocket, tuple[str, str]] = {}

    def add(self, room_id: str, player_id: str, websocket: WebSocket) -> None:
        """登记房间广播与玩家单播索引，支持同一玩家多标签页重连。"""

        self._rooms.setdefault(room_id, set()).add(websocket)
        identity = (room_id, player_id)
        self._players.setdefault(identity, set()).add(websocket)
        self._identity_by_socket[websocket] = identity

    def remove(self, room_id: str, websocket: WebSocket) -> None:
        connections = self._rooms.get(room_id)
        if connections is None:
            return
        connections.discard(websocket)
        if not connections:
            del self._rooms[room_id]
        identity = self._identity_by_socket.pop(websocket, None)
        if identity is not None:
            player_connections = self._players.get(identity)
            if player_connections is not None:
                player_connections.discard(websocket)
                if not player_connections:
                    del self._players[identity]

    def player_connections(self, room_id: str, player_id: str) -> tuple[WebSocket, ...]:
        """返回玩家当前连接快照，避免发送期间断线修改原集合。"""

        return tuple(self._players.get((room_id, player_id), ()))

    def player_ids(self, room_id: str) -> tuple[str, ...]:
        """返回房间内当前有连接的玩家，供逐玩家生成安全视图。"""

        return tuple(
            player_id
            for candidate_room_id, player_id in self._players
            if candidate_room_id == room_id
        )

    async def send_to_player(self, room_id: str, player_id: str, message: dict) -> None:
        """向玩家的全部标签页单播同一份玩家安全事件。"""

        for websocket in self.player_connections(room_id, player_id):
            with contextlib.suppress(Exception):
                await websocket.send_json(message)

    async def broadcast(self, room_id: str, message: dict) -> None:
        # 复制一份快照再遍历：广播过程中某个连接掉线触发 remove() 会改动
        # 原集合，直接遍历原集合会撞上"运行时改变集合大小"的异常。
        for websocket in list(self._rooms.get(room_id, ())):
            # 发送失败（连接已经断了但还没走到 disconnect 清理）忽略，
            # 交给该连接自己的 receive 循环去 remove()。
            with contextlib.suppress(Exception):
                await websocket.send_json(message)


manager = ConnectionManager()
