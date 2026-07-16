"""Service 层：房间 + 模组 + 游戏目录的数据访问和业务操作。

issue #77 之前是内存字典 stub，本期切换为对 `rooms`/`players`/`games`/
`game_systems`/`scenarios`/`events` 等表的真实 SQLAlchemy 读写——进程重启后
房间/玩家数据不再丢失。角色卡相关操作已拆到 service/character.py（issue #77
决策：`auth`/`room`/`character`/`ws` 四个 service 各自独立切换）。
"""

import random
import string
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_implemented
from app.dto.game import GameRead, GameSystemRead, RulesetRead
from app.dto.module import ModuleDetailRead
from app.dto.replay import ReplayEventRead, RoomSummaryRead
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
from app.models.content import Game, GameSystem, Scenario
from app.models.event import Event
from app.models.room import Player, Room
from app.models.user import User


class RoomNotFoundError(ValueError):
    """房间不存在。"""


class ModuleNotFoundError(ValueError):
    """模组 / 游戏 / 规则系统不存在。"""


class RoomAuthenticationError(PermissionError):
    """未提供有效的房间身份凭证。"""


class RoomAuthorizationError(PermissionError):
    """当前玩家无权执行房主操作。"""


class RoomConflictError(RuntimeError):
    """房间状态不允许当前操作（通用冲突，没有更具体的业务错误码可用时兜底）。"""


class RoomFullError(RuntimeError):
    """房间人数已满，无法加入。"""


class ModuleNotSelectedError(RuntimeError):
    """房间还没选定模组，无法开始游戏。"""


class CharacterIncompleteError(RuntimeError):
    """还有玩家未完成建卡，无法正式开局。"""


# ── 内部辅助 ──────────────────────────────────────


async def _generate_room_code(db: AsyncSession) -> str:
    """生成 6 位大写字母+数字房间码，避免碰撞。"""
    while True:
        code = "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        existing = await db.scalar(select(Room).where(Room.room_code == code))
        if existing is None:
            return code


async def find_room_by_id(db: AsyncSession, room_id: str) -> Room:
    room = await db.get(Room, room_id)
    if room is None:
        raise RoomNotFoundError("房间不存在")
    return room


async def get_player_by_reconnect_token(db: AsyncSession, reconnect_token: str | None) -> Player:
    """按重连凭证查玩家——房间/角色相关接口共用的身份校验入口
    （service/character.py 也会调用这个函数）。"""
    if reconnect_token is None:
        raise RoomAuthenticationError("缺少重连凭证")
    player = await db.scalar(select(Player).where(Player.reconnect_token == reconnect_token))
    if player is None:
        raise RoomAuthenticationError("重连凭证无效")
    return player


async def _require_host(db: AsyncSession, room: Room, reconnect_token: str | None) -> Player:
    player = await get_player_by_reconnect_token(db, reconnect_token)
    if player.room_id != room.id or player.id != room.host_player_id:
        raise RoomAuthorizationError("仅房主可以执行此操作")
    return player


async def require_room_member(
    db: AsyncSession, room_id: str, reconnect_token: str | None
) -> Player:
    """校验 reconnect_token 对应的玩家确实属于这个房间——复盘/回放这类"只有
    参与者能看"的接口用。否则 roomId 会被公开房间预览暴露，任何人凭 roomId 就
    能把整局的事件日志拉走（PR #78 review 指出）。"""
    player = await get_player_by_reconnect_token(db, reconnect_token)
    if player.room_id != room_id:
        raise RoomAuthorizationError("你不是这个房间的成员")
    return player


async def _module_title(db: AsyncSession, scenario_id: str | None) -> str | None:
    if scenario_id is None:
        return None
    scenario = await db.get(Scenario, scenario_id)
    return scenario.title if scenario is not None else None


async def _to_room_preview(db: AsyncSession, room: Room) -> RoomPreview:
    result = await db.scalars(select(Player).where(Player.room_id == room.id))
    room_players = list(result)
    return RoomPreview(
        room_id=room.id,
        room_code=room.room_code,
        room_name=room.room_name,
        phase=room.phase,
        story_started=room.phase != "Lobby",
        module_title=await _module_title(db, room.scenario_id),
        player_count=len(room_players),
        max_players=room.max_players,
        # 显式映射而不是 model_validate(p)：DTO 字段是 player_id，但 ORM Player
        # 的主键属性叫 id，from_attributes 按字段名找 p.player_id 会 missing。
        players=[
            RoomPlayerRead(
                player_id=p.id,
                nickname=p.nickname,
                is_host=p.is_host,
                ready=p.ready,
                has_character=p.has_character,
            )
            for p in room_players
        ],
    )


# ── 房间 ──────────────────────────────────────


async def create_room(db: AsyncSession, payload: RoomCreate, user: User | None) -> RoomCreateResult:
    """创建房间，返回房间身份信息。

    `user` 是可选的当前登录账号（由 controller 从 Authorization 头解析，查不到
    也不报错）——REST 创建房间接口本期不强制要求登录，带了有效登录态就把
    `Room.host_user_id`/`Player.user_id` 关联上，没带就留空（详见
    `models/room.py` 里 `Room.host_user_id` 的注释）。
    """
    room_code = await _generate_room_code(db)
    now = datetime.now(UTC)

    room = Room(
        room_code=room_code,
        room_name=payload.room_name,
        max_players=payload.max_players,
        phase="Lobby",
        host_user_id=user.id if user else None,
    )
    db.add(room)
    await db.flush()  # 拿到 room.id

    player = Player(
        room_id=room.id,
        user_id=user.id if user else None,
        nickname=payload.nickname or "房主",
        is_host=True,
        joined_at=now,
    )
    db.add(player)
    await db.flush()  # 拿到 player.id

    room.host_player_id = player.id
    await db.commit()

    return RoomCreateResult(
        room_id=room.id,
        room_code=room.room_code,
        reconnect_token=player.reconnect_token,
        player_id=player.id,
    )


async def join_room(
    db: AsyncSession, room_code: str, payload: JoinRoomBody, user: User | None
) -> RoomCreateResult:
    """用房间码加入房间。"""
    room = await db.scalar(select(Room).where(Room.room_code == room_code))
    if room is None:
        raise RoomNotFoundError("房间不存在")
    if room.phase != "Lobby":
        raise RoomConflictError("游戏已开始，无法加入房间")

    count_result = await db.scalars(select(Player).where(Player.room_id == room.id))
    player_count = len(list(count_result))
    if player_count >= room.max_players:
        raise RoomFullError("房间人数已满")

    player = Player(
        room_id=room.id,
        user_id=user.id if user else None,
        nickname=payload.nickname or "玩家",
        is_host=False,
        joined_at=datetime.now(UTC),
    )
    db.add(player)
    await db.commit()

    return RoomCreateResult(
        room_id=room.id,
        room_code=room_code,
        reconnect_token=player.reconnect_token,
        player_id=player.id,
    )


async def get_room_preview(db: AsyncSession, room_code: str) -> RoomPreview | None:
    """获取房间信息 + 玩家列表。"""
    room = await db.scalar(select(Room).where(Room.room_code == room_code))
    if room is None:
        return None
    return await _to_room_preview(db, room)


async def select_module(
    db: AsyncSession, room_id: str, payload: SelectModuleBody, reconnect_token: str | None
) -> None:
    """房主选定模组。"""
    room = await find_room_by_id(db, room_id)
    await _require_host(db, room, reconnect_token)
    if room.phase != "Lobby":
        raise RoomConflictError("只能在大厅阶段选择模组")

    scenario = await db.get(Scenario, payload.module_id)
    if scenario is None:
        raise ModuleNotFoundError("模组不存在")

    room.scenario_id = scenario.id
    room.system_id = scenario.game_system_id
    system = await db.get(GameSystem, scenario.game_system_id)
    room.game_id = system.game_id if system is not None else None
    room.attribute_gen_method = payload.attribute_gen_method
    await db.commit()


async def start_story(db: AsyncSession, room_id: str, reconnect_token: str | None) -> None:
    """房主在大厅点"开始游戏"，只推进到 Building（背景介绍 + 建卡）阶段。

    真正的"正式开局"（phase 变成 InGame）由 WS 的 game.start 事件触发
    （见 begin_game），必须等全员建完角色才能发生——大厅这一步只是放行玩家
    进入背景介绍和建卡流程，两者是有意分开的两个阶段。
    """
    room = await find_room_by_id(db, room_id)
    await _require_host(db, room, reconnect_token)
    if room.phase != "Lobby":
        raise RoomConflictError("只有大厅阶段可以开始游戏")
    if room.scenario_id is None:
        raise ModuleNotSelectedError("请先选择模组")
    room.phase = "Building"
    await db.commit()


async def get_player(db: AsyncSession, player_id: str) -> Player | None:
    """按 player_id 直接查玩家（WS 层用客户端声明的 playerId 校验绑定用）。"""
    return await db.get(Player, player_id)


async def set_player_ready(db: AsyncSession, player_id: str, ready: bool) -> None:
    """WS player.ready 事件：切换大厅准备状态。"""
    player = await db.get(Player, player_id)
    if player is not None:
        player.ready = ready
        await db.commit()


async def set_player_connected(db: AsyncSession, player_id: str, connected: bool) -> None:
    """WS 连接建立/断开时维护 `Player.connected`（room.rejoin 断线重连判断用，
    本期只维护状态不接真实重连逻辑）。"""
    player = await db.get(Player, player_id)
    if player is not None:
        player.connected = connected
        if not connected:
            player.left_at = datetime.now(UTC)
        await db.commit()


async def begin_game(db: AsyncSession, room_id: str, player_id: str) -> None:
    """WS game.start 事件：全员建完角色后，房主正式开局（Building → InGame）。"""
    room = await find_room_by_id(db, room_id)
    player = await db.get(Player, player_id)
    if player is None or player.room_id != room.id or player.id != room.host_player_id:
        raise RoomAuthorizationError("仅房主可以开始游戏")
    if room.phase != "Building":
        raise RoomConflictError("只有背景介绍/建卡阶段可以正式开局")
    result = await db.scalars(select(Player).where(Player.room_id == room.id))
    room_players = list(result)
    if not room_players or not all(p.has_character for p in room_players):
        raise CharacterIncompleteError("还有玩家未完成建卡")
    room.phase = "InGame"
    room.started_at = datetime.now(UTC)
    await db.commit()


async def list_my_rooms(db: AsyncSession, reconnect_token: str | None) -> list[MyRoomSummary]:
    """根据重连凭证获取当前玩家加入的房间（一个重连凭证只对应一名玩家/一个房间）。"""
    player = await get_player_by_reconnect_token(db, reconnect_token)
    room = await db.get(Room, player.room_id)
    if room is None:
        return []
    count_result = await db.scalars(select(Player).where(Player.room_id == room.id))
    player_count = len(list(count_result))
    return [
        MyRoomSummary(
            room_id=room.id,
            room_code=room.room_code,
            room_name=room.room_name,
            phase=room.phase,
            module_title=await _module_title(db, room.scenario_id),
            player_count=player_count,
            max_players=room.max_players,
            updated_at=room.updated_at,
        )
    ]


async def end_game(db: AsyncSession, room_id: str, reconnect_token: str | None) -> None:
    """房主结束游戏，房间状态标记为已完成。"""
    room = await find_room_by_id(db, room_id)
    await _require_host(db, room, reconnect_token)
    if room.phase != "InGame":
        raise RoomConflictError("只有进行中的游戏可以结束")
    room.phase = "Completed"
    room.ended_at = datetime.now(UTC)
    await db.commit()


# ── 游戏 / 规则系统 / 模组目录 ──────────────────────────────


async def list_games(db: AsyncSession) -> list[GameRead]:
    """GET /api/v1/games —— 游戏大类列表。"""
    result = await db.scalars(select(Game))
    return [GameRead.model_validate(g) for g in result]


async def list_game_systems(db: AsyncSession, game_id: str) -> list[GameSystemRead]:
    """GET /api/v1/games/{gameId}/systems —— 大类下的规则系统列表。"""
    game = await db.get(Game, game_id)
    if game is None:
        raise ModuleNotFoundError("游戏大类不存在")
    result = await db.scalars(select(GameSystem).where(GameSystem.game_id == game_id))
    return [GameSystemRead.model_validate(s) for s in result]


# COC7 建卡目录的最小示例数据（没有真实的规则数据管理界面，写死一份保证
# `GET /systems/{systemId}/ruleset` 有内容可用；GameSystem.ruleset 列如果
# 填了真实数据会优先使用它）。
_DEFAULT_COC7_RULESET = RulesetRead(
    attributes=["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU"],
    skills=["图书馆使用", "侦查", "聆听", "潜行", "闪避", "説服", "急救", "驾驶"],
    occupations=["私家侦探", "记者", "医生", "教授", "警察", "古董商"],
)


async def get_ruleset(db: AsyncSession, system_id: str) -> RulesetRead:
    """GET /api/v1/systems/{systemId}/ruleset —— 建卡所需规则数据。"""
    system = await db.get(GameSystem, system_id)
    if system is None:
        raise ModuleNotFoundError("规则系统不存在")
    if system.ruleset:
        return RulesetRead.model_validate(system.ruleset)
    return _DEFAULT_COC7_RULESET


async def list_modules(db: AsyncSession) -> list[ModuleRead]:
    """获取可用模组列表。"""
    result = await db.scalars(select(Scenario))
    return [ModuleRead.model_validate(s) for s in result]


async def get_module_detail(db: AsyncSession, module_id: str) -> ModuleDetailRead | None:
    """GET /api/v1/modules/{moduleId} —— 模组详情。"""
    scenario = await db.get(Scenario, module_id)
    if scenario is None:
        return None
    return ModuleDetailRead.model_validate(scenario)


# ── 复盘 / 事件回放 ──────────────────────────────────────


async def record_event(
    db: AsyncSession, room_id: str, player_id: str | None, event_type: str, payload: dict
) -> None:
    """写入一条房间事件（issue #77 才真正打通的闭环——原来"不记 EventLog"是
    已知缺口，本期由 ws.py 在 narration.push / action.submit 时调用这个函数）。
    """
    db.add(Event(room_id=room_id, player_id=player_id, event_type=event_type, payload=payload))
    await db.commit()


async def get_replay(
    db: AsyncSession, room_id: str, reconnect_token: str | None
) -> list[ReplayEventRead]:
    """GET /api/v1/rooms/{roomId}/replay —— 逐条事件回放，按发生时间正序。

    先校验发起者是这个房间的成员（复盘是"只有参与者能看"的内容），再查事件。
    """
    await require_room_member(db, room_id, reconnect_token)
    result = await db.scalars(
        select(Event).where(Event.room_id == room_id).order_by(Event.created_at)
    )
    return [ReplayEventRead.model_validate(e) for e in result]


async def get_summary(db: AsyncSession, room_id: str) -> RoomSummaryRead:
    """GET /api/v1/rooms/{roomId}/summary —— 复盘摘要。

    复盘内容依赖 AI 编排生成（归 #48/#68），本期没有任何写入路径会真的填充
    `room_summaries` 表，直接走 NOT_IMPLEMENTED（issue 决策 7）。
    """
    raise not_implemented("复盘摘要依赖 AI 编排生成，本期尚未实现")
