"""Service 层：房间 + 模组的数据访问和业务操作。

目前为 MS1 stub 实现，使用内存字典模拟数据，方便前端关闭 mock 后验证接口连通性。
后续接入真实数据库后按照 examples.py service 的模式改为 SQLAlchemy 操作。
"""

import random
import string
import uuid
from datetime import UTC, datetime

from app.dto.character import CharacterDraftResult, CharacterUpdateBody
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
_characters: dict[str, dict] = {}

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


class RoomNotFoundError(ValueError):
    """房间或模组不存在。"""


class RoomAuthenticationError(PermissionError):
    """未提供有效的房间身份凭证。"""


class RoomAuthorizationError(PermissionError):
    """当前玩家无权执行房主操作。"""


class RoomConflictError(RuntimeError):
    """房间状态不允许当前操作。"""


def _generate_room_code() -> str:
    """生成 6 位大写字母+数字房间码，避免碰撞。"""
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        if code not in _rooms:
            return code


def _find_room_by_id(room_id: str) -> dict:
    for room in _rooms.values():
        if room["id"] == room_id:
            return room
    raise RoomNotFoundError("房间不存在")


def _get_player_by_token(reconnect_token: str | None) -> dict:
    if reconnect_token is None:
        raise RoomAuthenticationError("缺少重连凭证")
    for player in _players.values():
        if player["reconnect_token"] == reconnect_token:
            return player
    raise RoomAuthenticationError("重连凭证无效")


def _require_host(room: dict, reconnect_token: str | None) -> None:
    player = _get_player_by_token(reconnect_token)
    if player["room_id"] != room["id"] or player["id"] != room["host_player_id"]:
        raise RoomAuthorizationError("仅房主可以执行此操作")


def _module_title(module_id: str | None) -> str | None:
    if module_id is None:
        return None
    return next((module.title for module in _BUILTIN_MODULES if module.id == module_id), None)


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


async def select_module(
    room_id: str, payload: SelectModuleBody, reconnect_token: str | None
) -> None:
    """房主选定模组。"""
    room = _find_room_by_id(room_id)
    _require_host(room, reconnect_token)
    if room["phase"] != "Lobby":
        raise RoomConflictError("只能在大厅阶段选择模组")
    if not any(module.id == payload.module_id for module in _BUILTIN_MODULES):
        raise RoomNotFoundError("模组不存在")
    room["module_id"] = payload.module_id
    room["updated_at"] = datetime.now(UTC)


async def join_room(room_code: str, payload: JoinRoomBody) -> RoomCreateResult:
    """用房间码加入房间。"""
    room = _rooms.get(room_code)
    if room is None:
        raise RoomNotFoundError("房间不存在")
    if room["phase"] != "Lobby":
        raise RoomConflictError("游戏已开始，无法加入房间")

    player_count = sum(player["room_id"] == room["id"] for player in _players.values())
    if player_count >= room["max_players"]:
        raise RoomConflictError("房间人数已满")

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

    room_players = [p for p in _players.values() if p["room_id"] == room["id"]]

    return RoomPreview(
        room_id=room["id"],
        room_code=room_code,
        room_name=room["room_name"],
        phase=room["phase"],
        story_started=room["phase"] != "Lobby",
        module_title=_module_title(room["module_id"]),
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


async def start_story(room_id: str, reconnect_token: str | None) -> None:
    """房主在大厅点"开始游戏"，只推进到 Building（背景介绍 + 建卡）阶段。

    真正的"正式开局"（phase 变成 InGame）由 issue #60 里 WS 的 game.start
    事件触发（见 begin_game），必须等全员建完角色才能发生——大厅这一步只是
    放行玩家进入背景介绍和建卡流程，两者是有意分开的两个阶段。
    """
    room = _find_room_by_id(room_id)
    _require_host(room, reconnect_token)
    if room["phase"] != "Lobby":
        raise RoomConflictError("只有大厅阶段可以开始游戏")
    if room["module_id"] is None:
        raise RoomConflictError("请先选择模组")
    room["phase"] = "Building"
    room["updated_at"] = datetime.now(UTC)


def get_player(player_id: str) -> dict | None:
    """按 player_id 直接查玩家（WS 层用客户端声明的 playerId 校验绑定用）。"""
    return _players.get(player_id)


async def set_player_ready(player_id: str, ready: bool) -> None:
    """WS player.ready 事件：切换大厅准备状态。"""
    player = _players.get(player_id)
    if player is not None:
        player["ready"] = ready


async def begin_game(room_id: str, player_id: str) -> None:
    """WS game.start 事件：全员建完角色后，房主正式开局（Building → InGame）。"""
    room = _find_room_by_id(room_id)
    player = _players.get(player_id)
    if player is None or player["room_id"] != room["id"] or player["id"] != room["host_player_id"]:
        raise RoomAuthorizationError("仅房主可以开始游戏")
    if room["phase"] != "Building":
        raise RoomConflictError("只有背景介绍/建卡阶段可以正式开局")
    room_players = [p for p in _players.values() if p["room_id"] == room["id"]]
    if not room_players or not all(p["has_character"] for p in room_players):
        raise RoomConflictError("还有玩家未完成建卡")
    room["phase"] = "InGame"
    room["updated_at"] = datetime.now(UTC)


async def list_my_rooms(reconnect_token: str | None) -> list[MyRoomSummary]:
    """根据重连凭证获取当前玩家加入的房间。"""
    player = _get_player_by_token(reconnect_token)
    summaries: list[MyRoomSummary] = []
    for room in _rooms.values():
        if room["id"] != player["room_id"]:
            continue
        room_players = [p for p in _players.values() if p["room_id"] == room["id"]]
        summaries.append(
            MyRoomSummary(
                room_id=room["id"],
                room_code=room["room_code"],
                room_name=room["room_name"],
                phase=room["phase"],
                module_title=_module_title(room["module_id"]),
                player_count=len(room_players),
                max_players=room["max_players"],
                updated_at=room["updated_at"],
            )
        )
    return summaries


async def create_character_draft(room_id: str, reconnect_token: str | None) -> CharacterDraftResult:
    """房间内玩家创建一份角色草稿。"""
    room = _find_room_by_id(room_id)
    player = _get_player_by_token(reconnect_token)
    if player["room_id"] != room["id"]:
        raise RoomAuthorizationError("你不在这个房间里")

    character_id = str(uuid.uuid4())
    _characters[character_id] = {
        "id": character_id,
        "room_id": room_id,
        "player_id": player["id"],
        "status": "draft",
    }
    return CharacterDraftResult(character_id=character_id, status="draft")


def _get_own_character(room_id: str, character_id: str, reconnect_token: str | None) -> dict:
    player = _get_player_by_token(reconnect_token)
    character = _characters.get(character_id)
    if character is None or character["room_id"] != room_id:
        raise RoomNotFoundError("角色不存在")
    if character["player_id"] != player["id"]:
        raise RoomAuthorizationError("不能编辑其他玩家的角色")
    return character


async def update_character(
    room_id: str,
    character_id: str,
    payload: CharacterUpdateBody,
    reconnect_token: str | None,
) -> None:
    """保存建卡向导算好的完整角色数据。"""
    character = _get_own_character(room_id, character_id, reconnect_token)
    character["name"] = payload.name
    character["attributes"] = payload.attributes
    character["derived_stats"] = payload.derived_stats
    character["skills"] = payload.skills
    character["equipment"] = [item.name for item in payload.equipment]
    character["occupation"] = payload.occupation
    character["background"] = payload.background
    character["notes"] = payload.notes


async def complete_character(room_id: str, character_id: str, reconnect_token: str | None) -> None:
    """标记建卡完成，同步把对应玩家的 has_character 置为 True。"""
    character = _get_own_character(room_id, character_id, reconnect_token)
    character["status"] = "complete"
    player = _players.get(character["player_id"])
    if player is not None:
        player["has_character"] = True


async def end_game(room_id: str, reconnect_token: str | None) -> None:
    """房主结束游戏，房间状态标记为已完成。"""
    room = _find_room_by_id(room_id)
    _require_host(room, reconnect_token)
    if room["phase"] != "InGame":
        raise RoomConflictError("只有进行中的游戏可以结束")
    room["phase"] = "Completed"
    room["updated_at"] = datetime.now(UTC)
