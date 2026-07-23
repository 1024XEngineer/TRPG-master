"""Service 层：房间 + 模组 + 游戏目录的数据访问和业务操作。

issue #77 之前是内存字典 stub，本期切换为对 `rooms`/`players`/`games`/
`game_systems`/`scenarios`/`events` 等表的真实 SQLAlchemy 读写——进程重启后
房间/玩家数据不再丢失。角色卡相关操作已拆到 service/character.py（issue #77
决策：`auth`/`room`/`character`/`ws` 四个 service 各自独立切换）。
"""

import secrets
import string
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_implemented
from app.core.narrator import NarrationContext
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
from app.models.room import Character, Player, Room
from app.models.user import User
from app.service import chat as chat_service


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


class RulesetNotConfiguredError(RuntimeError):
    """规则系统存在，但没有可用的规则数据，无法据此裁决建卡。"""


# ── 内部辅助 ──────────────────────────────────────


async def _generate_room_code(db: AsyncSession) -> str:
    """生成 6 位大写字母+数字房间码，避免碰撞。"""
    while True:
        code = "".join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
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


async def _room_identity(db: AsyncSession, room: Room, player: Player) -> RoomCreateResult:
    """组装「我在这个房间里是谁」——创建/加入/重连三条路径共用。

    带上 `character_id` 是为了让**换设备重连**真正可用（PR #110 review [1]）：
    客户端靠它才知道该去拉哪张角色卡，而在此之前这个 id 只在建卡那一刻由客户端
    自己存着——换台设备就永远拿不回来了，已经建完卡的人重连后会显示成"还没建卡"、
    被引导去建第二张。服务端本来就知道答案，直接给。
    """
    character = await db.scalar(select(Character).where(Character.player_id == player.id))
    return RoomCreateResult(
        room_id=room.id,
        room_code=room.room_code,
        reconnect_token=player.reconnect_token,
        player_id=player.id,
        character_id=character.id if character is not None else None,
    )


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


async def create_room(db: AsyncSession, payload: RoomCreate, user: User) -> RoomCreateResult:
    """创建房间，返回房间身份信息。

    `user` 是**必需**的当前登录账号（issue #106）。此前它是可选的，于是
    `host_user_id`/`user_id` 永远是 `null`，「我的游戏」只能退而按 reconnect_token
    查、跨设备找回无从谈起。登录本来就是 2026-07-11 拍板的硬性前提，这里只是让
    实现跟上那条前提。
    """
    room_code = await _generate_room_code(db)
    now = datetime.now(UTC)

    room = Room(
        room_code=room_code,
        room_name=payload.room_name,
        max_players=payload.max_players,
        phase="Lobby",
        host_user_id=user.id,
    )
    db.add(room)
    await db.flush()  # 拿到 room.id

    player = Player(
        room_id=room.id,
        user_id=user.id,
        nickname=payload.nickname or "房主",
        is_host=True,
        joined_at=now,
    )
    db.add(player)
    await db.flush()  # 拿到 player.id

    room.host_player_id = player.id
    await db.commit()

    return await _room_identity(db, room, player)


async def join_room(
    db: AsyncSession, room_code: str, payload: JoinRoomBody, user: User
) -> RoomCreateResult:
    """用房间码加入房间；**已经是成员则幂等返回既有身份**（issue #106）。

    改动前这里有两个各自独立的缺陷：

    1. 开头一律 `if room.phase != "Lobby": raise` —— 把「中途加入」和「掉线重连」
       当成同一件事拒掉。前者确实该拒（本期不做中途加入），后者是核心能力，
       结果就是刷新/断线后必现 409、回不到自己那局。
    2. 全程不检查调用者是不是已经在房间里，无条件新建 `Player` —— 同一个人重复
       加入会生成重复玩家行、虚增人数直到撞满员。前端注释写的「已是本房间玩家
       则幂等返回已有身份」是假的。

    幂等键取**账号**而不是 `reconnect_token`：后者存在浏览器会话里，换设备、清缓存
    就没了，而「换设备也能回到这局」正是账号体系被引入的理由。两者分工不变——
    账号解决跨设备/跨时间找回，`reconnect_token` 解决同一局内的快速重连。
    """
    room = await db.scalar(select(Room).where(Room.room_code == room_code))
    if room is None:
        raise RoomNotFoundError("房间不存在")

    # 先看是不是老成员：是的话直接把既有身份还回去，不受阶段和人数上限影响
    # （重连的人本来就已经占着那个位置，拿满员去拦他没有道理）。
    existing = await db.scalar(
        select(Player).where(Player.room_id == room.id, Player.user_id == user.id)
    )
    if existing is not None:
        return await _room_identity(db, room, existing)

    # 到这里说明是新人。新人只能在大厅阶段加入：游戏已经开始/结束之后再放人
    # 进来，等于中途加入，本期不做。
    if room.phase != "Lobby":
        raise RoomConflictError("游戏已开始，无法加入房间")

    count_result = await db.scalars(select(Player).where(Player.room_id == room.id))
    player_count = len(list(count_result))
    if player_count >= room.max_players:
        raise RoomFullError("房间人数已满")

    player = Player(
        room_id=room.id,
        user_id=user.id,
        nickname=payload.nickname or "玩家",
        is_host=False,
        joined_at=datetime.now(UTC),
    )
    # 上面那段「先查有没有、没有才插」是 check-then-act，两个并发的重连/加入请求
    # 会同时查到「不存在」然后各插一行（PR #110 review [2]）。真正的不变式由
    # `players` 的 `uq_players_room_user` 唯一约束保证，这里负责把撞上约束的那一方
    # **收敛成和先到者一样的结果**——毕竟两个请求想要的是同一件事。
    #
    # 🔴 必须用 SAVEPOINT（`begin_nested`）包住这次插入，不能直接 `commit()` 之后
    # 捕获再 `rollback()`：那样整个事务连同连接一起废掉，紧接着的重查要重新建连接，
    # 在异步驱动下会炸 `MissingGreenlet`——真实并发 curl 实测 10 个请求里有 2 个
    # 因此返回 500（pytest 的 ASGITransport 装置压不出并发，测不到这条）。
    # SAVEPOINT 只回滚到存档点，session 和连接都还活着，重查才做得下去。
    try:
        async with db.begin_nested():
            db.add(player)
            await db.flush()
    except IntegrityError:
        winner = await db.scalar(
            select(Player).where(Player.room_id == room.id, Player.user_id == user.id)
        )
        if winner is None:
            raise
        return await _room_identity(db, room, winner)

    await db.commit()
    return await _room_identity(db, room, player)


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


async def list_my_rooms(db: AsyncSession, user: User) -> list[MyRoomSummary]:
    """当前**账号**参与过的全部房间，最近活跃的排在前面（issue #106）。

    改动前这里是按 `reconnect_token` 查的，而一个重连凭证只对应一名玩家、一个
    房间——所以「我的游戏」实际上是「这个浏览器的最后一个房间」，换台设备就什么
    都看不到。账号体系当初正是为「换设备找回游戏」引入的，这里按 `user_id` 查才
    兑现了那个目的。

    ⚠️ 查询数量必须跟房间数**无关**。第一版在循环里逐个房间查人数、查模组标题，
    N 个房间要发约 `2N+2` 条查询（PR #110 review [3]）——这个接口正是本 issue 让它
    从「最多一个房间」变成「该账号全部房间」的，N 会真的长起来。下面改成先一次性
    把人数和模组标题聚合出来，再拼结果，总共 4 条查询封顶。
    """
    players = await db.scalars(select(Player).where(Player.user_id == user.id))
    room_ids = [p.room_id for p in players]
    if not room_ids:
        return []

    rooms = list(
        await db.scalars(select(Room).where(Room.id.in_(room_ids)).order_by(Room.updated_at.desc()))
    )

    # 每个房间的人数：一条 GROUP BY，不是一房一查
    count_rows = await db.execute(
        select(Player.room_id, func.count(Player.id))
        .where(Player.room_id.in_(room_ids))
        .group_by(Player.room_id)
    )
    counts = dict(count_rows.tuples().all())

    # 模组标题：把用到的 scenario_id 去重后一次查完
    scenario_ids = {room.scenario_id for room in rooms if room.scenario_id is not None}
    titles: dict[str, str] = {}
    if scenario_ids:
        title_rows = await db.execute(
            select(Scenario.id, Scenario.title).where(Scenario.id.in_(scenario_ids))
        )
        titles = dict(title_rows.tuples().all())

    return [
        MyRoomSummary(
            room_id=room.id,
            room_code=room.room_code,
            room_name=room.room_name,
            phase=room.phase,
            module_title=titles.get(room.scenario_id) if room.scenario_id else None,
            player_count=counts.get(room.id, 0),
            max_players=room.max_players,
            updated_at=room.updated_at,
        )
        for room in rooms
    ]


async def end_game(db: AsyncSession, room_id: str, reconnect_token: str | None) -> None:
    """房主结束游戏，房间状态标记为已完成。

    顺带清空该房间的讨论区聊天记录（issue #107）：聊天是临时工作记忆，不进
    复盘、随房间结束销毁；`end` 是目前房间唯一的后端终结点（没有单独的
    "退出房间"接口，见 #106 本期不做），清理只能挂在这里。
    """
    room = await find_room_by_id(db, room_id)
    await _require_host(db, room, reconnect_token)
    if room.phase != "InGame":
        raise RoomConflictError("只有进行中的游戏可以结束")
    room.phase = "Completed"
    room.ended_at = datetime.now(UTC)
    await chat_service.clear_room_chat(db, room.id)
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


async def get_ruleset(db: AsyncSession, system_id: str) -> RulesetRead:
    """GET /api/v1/systems/{systemId}/ruleset —— 建卡所需规则数据。

    真实数据来自 `GameSystem.ruleset`（`app/core/seed.py` seed 时用
    `app/core/coc7_content.py` 的权威数据写入）。issue #84 S1 之前这里有一份
    手写的三字符串数组兜底桩，加厚 schema 后跟 `RulesetRead` 新形状不兼容，
    且 seed 已经保证 COC7 系统一定带 ruleset，故删除——没有 ruleset 数据的
    系统（本期只有还没配置规则数据的自定义系统会出现这种情况）直接返回空
    目录，而不是伪造一份看起来正常但内容不对的数据。
    """
    system = await db.get(GameSystem, system_id)
    if system is None:
        raise ModuleNotFoundError("规则系统不存在")
    if system.ruleset:
        return RulesetRead.model_validate(system.ruleset)
    return RulesetRead(attributes=[], skills=[], occupations=[])


async def require_ruleset(db: AsyncSession, system_id: str) -> RulesetRead:
    """裁决路径专用的取数：拿不到可用规则数据就直接拒绝，不返回空目录。

    跟 `get_ruleset` 的区别是**用途**，不是数据源——两者读的是同一张表：

    - `get_ruleset` 服务于 `GET /systems/{id}/ruleset`（前端渲染用）。规则数据
      为空时返回空目录是合理的：前端拿到空目录就知道这个系统还没配规则。
    - `require_ruleset` 服务于**裁决**（建卡 `complete` 校验、`preview` 计算）。
      规则计算改参数注入后（issue #112），属性键/技能表/职业目录全部来自传入的
      `RulesetRead`，空目录会让校验退化成"零个约束"——空白角色卡一条问题都查不出
      来，`complete_character` 会把它标记成完成。校验闸门不能 fail-open，所以这里
      宁可报错也不放行。

    参数注入之前这条路径是安全的，因为属性键写死在 `coc7_rules` 的模块常量里，
    与规则数据是否存在无关；把数据源变成参数之后，"没有数据"就成了一种必须显式
    处理的输入。
    """
    ruleset = await get_ruleset(db, system_id)
    if not ruleset.attributes or not ruleset.occupations:
        raise RulesetNotConfiguredError("该规则系统尚未配置规则数据，无法建卡")
    return ruleset


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


# 叙事上下文里带多少条行动历史。取值权衡：太少 AI 上文接不住，太多白白烧
# token——单轮生成（非编排）的定位下 6 条足够撑起"延续刚才的场景"。
_NARRATION_HISTORY_LIMIT = 6


async def build_narration_context(
    db: AsyncSession, room_id: str, player_id: str, utterance: str
) -> NarrationContext:
    """为一次 action.submit 组装叙事生成的上下文（issue #107）。

    数据来源只有两处：房间关联的模组标题 + `events` 表里最近几条
    `action.submit`（**不读聊天表**——讨论区内容永远不进 LLM 上下文，这是
    #107 跟 AI 编排对齐的第 1 条约定，靠这里的代码结构保证）。

    ⚠️ 调用时序约定：ws.py 必须在 `record_event` 写入当前这条 action.submit
    **之前**调用本函数——这样查出来的历史天然不含当前这条（它会作为"玩家刚
    说的话"单独出现在 prompt 末尾，不该在历史里重复）。靠时序排除比靠
    "player_id+内容匹配"过滤可靠：玩家完全可能重复说过一模一样的话。

    Narrator（app/core/narrator.py）自己不查库，所有字段由这里备好传入。
    """
    player = await db.get(Player, player_id)
    nickname = player.nickname if player is not None else "玩家"

    room = await db.get(Room, room_id)
    module_title = await _module_title(db, room.scenario_id) if room is not None else None

    # 最近 N 条行动：按倒序取再反转成时间正序喂给模型。
    result = await db.execute(
        select(Event)
        .where(Event.room_id == room_id, Event.event_type == "action.submit")
        .order_by(Event.created_at.desc(), Event.id.desc())
        .limit(_NARRATION_HISTORY_LIMIT)
    )
    history = list(result.scalars())
    history.reverse()

    # 批量查昵称，不在循环里逐条查（N+1 的教训，PR #110 review [3]）
    speaker_ids = {e.player_id for e in history if e.player_id is not None}
    nicknames: dict[str, str] = {}
    if speaker_ids:
        rows = await db.execute(
            select(Player.id, Player.nickname).where(Player.id.in_(speaker_ids))
        )
        # Row 是 tuple 的子类但类型上不是 tuple[str, str]，直接喂 dict() 过不了
        # 类型检查——用 .tuples() 显式转成类型化元组再构造。
        nicknames = dict(rows.tuples().all())

    recent_actions = [
        f"{nicknames.get(e.player_id or '', '玩家')}: {e.payload.get('utterance', '')}"
        for e in history
    ]
    return NarrationContext(
        utterance=utterance,
        player_nickname=nickname,
        module_title=module_title,
        recent_actions=recent_actions,
    )


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
