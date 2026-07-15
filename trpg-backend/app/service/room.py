"""Service 层：房间 + 模组的数据访问和业务操作。

目前为 MS1 stub 实现，使用内存字典模拟数据，方便前端关闭 mock 后验证接口连通性。
后续接入真实数据库后按照 examples.py service 的模式改为 SQLAlchemy 操作。
"""

import random
import string
import uuid
from datetime import UTC, datetime

from app.dto.room import (
    JoinRoomBody,
    ModuleRead,
    MyRoomSummary,
    RoomCreate,
    RoomCreateResult,
    RoomPlayerRead,
    RoomPreview,
    SelectModuleBody,
)

# ── 内存数据存储（MS1 stub，后续替换为数据库） ──
_rooms: dict[str, dict] = {}
_players: dict[str, dict] = {}

# 内置模组（MS1 只有一款内置模拟模组）
_BUILTIN_MODULES: list[ModuleRead] = [
    ModuleRead(
        id=str(uuid.uuid4()),
        title="追书人（内置）",
        version="1.0.0",
        authors=["TRPG-master"],
        players_min=1,
        players_max=6,
        difficulty=1,
        estimated_duration="2-3 小时",
    ),
]


def _generate_room_code() -> str:
    """生成 6 位大写字母+数字房间码，避免碰撞。"""
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in _rooms:
            return code


async def create_room(payload: RoomCreate) -> RoomCreateResult:
    """创建房间，返回房间身份信息。"""
    room_id = str(uuid.uuid4())
    player_id = str(uuid.uuid4())
    reconnect_token = str(uuid.uuid4())
    room_code = _generate_room_code()
    now = datetime.now(UTC)

    room = {
        "id": room_id,
        "room_code": room_code,
        "room_name": payload.room_name,
        "max_players": payload.max_players,
        "phase": "Lobby",
        "host_player_id": player_id,
        "module_id": None,
        "created_at": now,
        "updated_at": now,
    }
    player = {
        "id": player_id,
        "room_id": room_id,
        "nickname": payload.nickname or "房主",
        "is_host": True,
        "ready": False,
        "has_character": False,
        "reconnect_token": reconnect_token,
        "created_at": now,
    }
    _rooms[room_code] = room
    _players[player_id] = player

    return RoomCreateResult(
        room_id=room_id,
        room_code=room_code,
        reconnect_token=reconnect_token,
        player_id=player_id,
    )


async def list_modules() -> list[ModuleRead]:
    """获取可用模组列表。"""
    return _BUILTIN_MODULES


async def select_module(room_id: str, payload: SelectModuleBody) -> None:
    """房主选定模组。"""
    for room in _rooms.values():
        if room["id"] == room_id:
            room["module_id"] = payload.module_id
            room["updated_at"] = datetime.now(UTC)
            return


async def join_room(room_code: str, payload: JoinRoomBody) -> RoomCreateResult:
    """用房间码加入房间。"""
    room = _rooms.get(room_code)
    if room is None:
        raise ValueError("房间不存在")

    player_id = str(uuid.uuid4())
    reconnect_token = str(uuid.uuid4())
    now = datetime.now(UTC)

    player = {
        "id": player_id,
        "room_id": room["id"],
        "nickname": payload.nickname or "玩家",
        "is_host": False,
        "ready": False,
        "has_character": False,
        "reconnect_token": reconnect_token,
        "created_at": now,
    }
    _players[player_id] = player

    return RoomCreateResult(
        room_id=room["id"],
        room_code=room_code,
        reconnect_token=reconnect_token,
        player_id=player_id,
    )


async def get_room_preview(room_code: str) -> RoomPreview | None:
    """获取房间信息 + 玩家列表。"""
    room = _rooms.get(room_code)
    if room is None:
        return None

    room_players = [
        p for p in _players.values() if p["room_id"] == room["id"]
    ]

    # 查找模组标题
    module_title = None
    if room["module_id"]:
        for m in _BUILTIN_MODULES:
            if m.id == room["module_id"]:
                module_title = m.title
                break

    return RoomPreview(
        room_id=room["id"],
        room_code=room_code,
        room_name=room["room_name"],
        phase=room["phase"],
        story_started=room["phase"] != "Lobby",
        module_title=module_title,
        player_count=len(room_players),
        max_players=room["max_players"],
        players=[
            RoomPlayerRead(
                player_id=p["id"],
                nickname=p["nickname"],
                is_host=p["is_host"],
                ready=p["ready"],
                has_character=p["has_character"],
            )
            for p in room_players
        ],
    )


async def start_story(room_id: str) -> None:
    """房主开始游戏，将房间阶段推进到 InGame。"""
    for room in _rooms.values():
        if room["id"] == room_id:
            room["phase"] = "InGame"
            room["updated_at"] = datetime.now(UTC)
            return
    raise ValueError("房间不存在")


async def list_my_rooms(player_id: str | None = None) -> list[MyRoomSummary]:
    """获取我的房间列表（MS1 stub：返回所有房间）。"""
    summaries: list[MyRoomSummary] = []
    for room in _rooms.values():
        room_players = [
            p for p in _players.values() if p["room_id"] == room["id"]
        ]
        # 查找模组标题
        module_title = None
        if room["module_id"]:
            for m in _BUILTIN_MODULES:
                if m.id == room["module_id"]:
                    module_title = m.title
                    break
        summaries.append(
            MyRoomSummary(
                room_id=room["id"],
                room_code=room["room_code"],
                room_name=room["room_name"],
                phase=room["phase"],
                module_title=module_title,
                player_count=len(room_players),
                max_players=room["max_players"],
                updated_at=room["updated_at"],
            )
        )
    return summaries


async def end_game(room_id: str) -> None:
    """房主结束游戏，房间状态标记为已完成。"""
    for room in _rooms.values():
        if room["id"] == room_id:
            room["phase"] = "Completed"
            room["updated_at"] = datetime.now(UTC)
            return
    raise ValueError("房间不存在")
