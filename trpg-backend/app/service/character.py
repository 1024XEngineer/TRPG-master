"""Service 层：角色（调查员）建卡（issue #59，issue #77 切换为真实 ORM 读写
+ 补齐服务端权威掷骰 / 角色卡模板两个新协议位置）。

建卡流程分两段：POST 创建草稿 → PATCH 保存完整数据 → POST complete 标记完成。
房间/重连凭证校验复用 service/room.py 的 `get_player_by_reconnect_token`——
角色卡操作跟房间操作共用同一套"这是房间里的哪个玩家"身份体系。
"""

import random
from dataclasses import asdict, replace

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.coc7_character_generation import generate_character_draft
from app.core.coc7_content import build_coc7_ruleset
from app.core.coc7_rules import (
    GENERATION_POINT_BUY,
    GENERATION_ROLL,
    ValidationIssue,
    compute_derived_stats,
    compute_preview,
    validate_age,
    validate_character,
)
from app.core.seed import BUILTIN_SYSTEM_ID
from app.dto.character import (
    CharacterComputeResult,
    CharacterDraftResult,
    CharacterPreviewRequest,
    CharacterRead,
    CharacterTemplateCreateBody,
    CharacterTemplateRead,
    CharacterTemplateUpdateBody,
    CharacterUpdateBody,
    QuickGenerateRequest,
    QuickGenerateResult,
    RollAttributesResult,
    SystemQuickGenerateResult,
)
from app.dto.character_background import CharacterBackgroundContext, CharacterBackgroundSkill
from app.dto.game import RulesetRead
from app.models.content import GameSystem
from app.models.room import Character, Player, Room
from app.models.user import UserCharacterTemplate
from app.service.character_background import CharacterBackgroundService
from app.service.room import (
    RoomAuthorizationError,
    RoomConflictError,
    find_room_by_id,
    get_player_by_reconnect_token,
    require_ruleset,
)


class CharacterNotFoundError(ValueError):
    """角色不存在。"""


class CharacterInvalidDataError(ValueError):
    """卡库卡的建卡态数据形状不合法（字段类型或长度），映射成 422。"""


class CharacterInvalidError(ValueError):
    """建卡数据未通过 COC7 权威校验（issue #84 S2）：`complete_character`
    落库前的最后一道闸门，不能只靠前端本地拦——S3 阶段前端本地规则计算会被
    删掉，这里是唯一权威来源。`issues` 是结构化校验报告，供 controller 层
    转成 `AppException.details` 带给前端。"""

    def __init__(self, issues: list[ValidationIssue]) -> None:
        self.issues = issues
        summary = "；".join(f"[{issue.code}] {issue.message}" for issue in issues)
        super().__init__(f"角色卡未通过校验：{summary}")


def _require_character_editable(room: Room) -> None:
    """正式开局后 Character 已复制为 ActorState，源角色卡必须保持冻结。"""
    if room.phase not in {"Lobby", "Building"}:
        raise RoomConflictError("游戏已经正式开局，房间角色卡已锁定")


async def _mark_character_modified(db: AsyncSession, character: Character) -> None:
    """把一次房间建卡写入标记为尚未完成。

    以前这里还会顺手 `based_on_template_id = None`，因为那个列同时被当成
    「自动保存的去重闩」用：清空它，下一次 complete 才会再存一张用户卡。#337
    把方向倒了过来——卡库卡是玩家自己的资产，只由显式保存产生，房间卡是它的
    一份拷贝——这个列于是退回纯粹的出处记录。出处不因为玩家改了几笔就不成立，
    所以不再清空。
    """
    if character.status != "complete":
        return
    character.status = "draft"
    player = await db.get(Player, character.player_id)
    if player is not None:
        player.has_character = False


def _character_template_data(character: Character) -> dict[str, object]:
    """提取可跨房间复用的建卡态字段，不保存任何局内 Actor 状态。"""
    return {
        "generation_method": character.generation_method,
        "name": character.name,
        "age": character.age,
        "gender": character.gender,
        "residence": character.residence or "",
        "birthplace": character.birthplace or "",
        "attributes": dict(character.attributes or {}),
        "skills": dict(character.skills or {}),
        "occupation_choice_skill_ids": (
            list(character.occupation_choice_skill_ids)
            if character.occupation_choice_skill_ids is not None
            else None
        ),
        "equipment": list(character.equipment or []),
        "occupation": character.occupation,
        "background": character.background or "",
        "notes": character.notes or "",
    }


# `characters` 上这几列的长度上限。卡库卡的 `data` 是客户端自由写入的 JSON，
# 只校验总大小的话，一条 200 字的 name 能顺利存进卡库、却在播种时撑爆
# `characters.name VARCHAR(100)`——SQLite 不强制长度所以本地和测试都看不见，
# PostgreSQL 上是一个合法保存的卡永远播种不了（DataError → 500）。在保存卡库卡
# 这一步就拦住，而不是等到播种时才失败。
_SEEDABLE_MAX_LENGTHS: dict[str, int] = {
    "name": 100,
    "gender": 20,
    "residence": 100,
    "birthplace": 100,
    "occupation": 100,
    "background": 4000,
    "notes": 4000,
}


def _require_seedable_lengths(data: dict) -> None:
    for key, limit in _SEEDABLE_MAX_LENGTHS.items():
        value = data.get(key)
        if value is None:
            continue
        if not isinstance(value, str):
            raise CharacterInvalidDataError(f"角色卡字段 {key} 必须是字符串")
        if len(value) > limit:
            raise CharacterInvalidDataError(f"角色卡字段 {key} 超过 {limit} 字上限")


def _seed_character_from_template(character: Character, template: UserCharacterTemplate) -> None:
    """把卡库卡的建卡态字段拷进一张新的房间草稿。

    只认 `_character_template_data()` 写出来的那几个键，逐个取值而不是整体
    `**data`：`data` 是 JSON 列，多出来的键不该变成房间角色卡的字段，缺失的键
    要落到与「从零建卡」一致的默认值上，而不是 None 一路带下去。

    局内状态（HP / 理智 / 疯狂）本来就不在 `data` 里，这里也不会凭空造：
    `derived_stats` 留空，等 complete 时服务端按属性权威重算。
    """
    data = dict(template.data or {})
    character.based_on_template_id = template.id
    character.generation_method = data.get("generation_method") or GENERATION_POINT_BUY
    character.name = data.get("name")
    character.age = data.get("age")
    character.gender = data.get("gender")
    character.residence = data.get("residence") or ""
    character.birthplace = data.get("birthplace") or ""
    character.attributes = dict(data.get("attributes") or {})
    character.skills = dict(data.get("skills") or {})
    character.occupation_choice_skill_ids = data.get("occupation_choice_skill_ids")
    character.equipment = list(data.get("equipment") or [])
    character.occupation = data.get("occupation")
    character.background = data.get("background") or ""
    character.notes = data.get("notes") or ""


async def create_character_draft(
    db: AsyncSession, room_id: str, reconnect_token: str | None, based_on_template_id: str | None
) -> CharacterDraftResult:
    """房间内玩家创建一份角色草稿。

    `based_on_template_id`（#337 落地）：带了这个字段就从玩家自己的卡库卡播种
    一张新草稿，把建卡态字段整体拷进来。拷贝之后房间角色卡是自足的，卡库卡后来
    改了或删了都不影响这一局。

    已经有草稿时**带模板会 409**，不会静默返回既有那张。前端多半在进页面时就建好
    了草稿，所以「从卡库选卡」几乎必然撞上它；返回 201 加一张原封不动的空卡，看
    起来是成功的、实际什么都没发生。要不要冲掉玩家已有的草稿，得让玩家自己决定。
    """
    room = await find_room_by_id(db, room_id)
    _require_character_editable(room)
    player = await get_player_by_reconnect_token(db, reconnect_token)
    if player.room_id != room.id:
        raise RoomAuthorizationError("你不在这个房间里")

    existing = await db.scalar(
        select(Character).where(
            Character.room_id == room_id,
            Character.player_id == player.id,
        )
    )
    if existing is not None:
        if based_on_template_id is not None:
            raise RoomConflictError("本房间已有角色卡草稿，不能直接套用卡库角色卡")
        return CharacterDraftResult(
            character_id=existing.id,
            status=existing.status,
        )

    character = Character(room_id=room_id, player_id=player.id, status="draft")
    if based_on_template_id is not None:
        if player.user_id is None:
            raise RoomAuthorizationError("匿名玩家没有角色卡库")
        template = await _own_template(db, player.user_id, based_on_template_id)
        # 规则系统不匹配就拒绝：COC7 的卡拿去玩别的系统，属性和技能对不上，
        # 与其静默拷进去等 complete 时校验炸掉，不如在这里说清楚。
        room_system_id = room.system_id or BUILTIN_SYSTEM_ID
        if template.system_id != room_system_id:
            raise RoomConflictError("这张角色卡属于其他规则系统，不能用在本房间")
        _seed_character_from_template(character, template)
    db.add(character)
    try:
        await db.commit()
    except IntegrityError:
        # A concurrent request may have won the unique (room, player) insert.
        # Roll back the failed transaction, then return that same authoritative
        # row instead of leaking a database exception as HTTP 500.
        await db.rollback()
        existing = await db.scalar(
            select(Character).where(
                Character.room_id == room_id,
                Character.player_id == player.id,
            )
        )
        if existing is None:
            raise
        # 并发下另一个请求先建成了草稿。带模板的请求在这里也必须报冲突，否则
        # 前置查询挡住的那条路会从这里绕回来——又变成「201 成功但模板没应用」。
        if based_on_template_id is not None:
            raise RoomConflictError("本房间已有角色卡草稿，不能直接套用卡库角色卡") from None
        return CharacterDraftResult(
            character_id=existing.id,
            status=existing.status,
        )
    return CharacterDraftResult(character_id=character.id, status=character.status)


async def _get_own_character(
    db: AsyncSession, room_id: str, character_id: str, reconnect_token: str | None
) -> Character:
    player = await get_player_by_reconnect_token(db, reconnect_token)
    character = await db.get(Character, character_id)
    if character is None or character.room_id != room_id:
        raise CharacterNotFoundError("角色不存在")
    if character.player_id != player.id:
        raise RoomAuthorizationError("不能编辑其他玩家的角色")
    return character


async def update_character(
    db: AsyncSession,
    room_id: str,
    character_id: str,
    payload: CharacterUpdateBody,
    reconnect_token: str | None,
) -> None:
    """保存建卡向导算好的完整角色数据。"""
    character = await _get_own_character(db, room_id, character_id, reconnect_token)
    room = await find_room_by_id(db, room_id)
    _require_character_editable(room)
    await _mark_character_modified(db, character)

    # PR #97 review [1]：`roll` 这个来源标记不能跨越「客户端自己重填了属性」。
    # `roll_attributes` 会把它置成 roll，complete 时据此跳过 480 点预算校验
    # （骰子结果本来就不受点数购买法约束）；但这个 PATCH 接受客户端任意属性，
    # 标记原样留着的话，先掷一次、再把 8 项全顶到 90 提交，就能绕开预算过关。
    # 属性跟掷出来那份不一致就说明是客户端填的，来源退回点数购买法。
    if (
        character.generation_method == GENERATION_ROLL
        and payload.attributes != character.attributes
    ):
        character.generation_method = GENERATION_POINT_BUY

    character.name = payload.name
    character.age = payload.age
    character.gender = payload.gender
    character.residence = payload.residence
    character.birthplace = payload.birthplace
    character.attributes = payload.attributes
    character.derived_stats = payload.derived_stats
    character.skills = payload.skills
    character.occupation_choice_skill_ids = payload.occupation_choice_skill_ids
    character.equipment = [item.name for item in payload.equipment]
    character.occupation = payload.occupation
    character.background = payload.background
    character.notes = payload.notes
    character.version += 1
    await db.commit()


async def _resolve_ruleset(db: AsyncSession, room: Room) -> RulesetRead:
    """决定这个房间的建卡该用哪份规则数据（issue #112：`coc7_rules` 本身对
    具体是哪个规则系统无知，取数据这件事由 service 层负责）。

    房间已经选了模组（`room.system_id` 有值）就用那个规则系统的 ruleset；
    房间还没选模组（比如还在大厅、玩家提前建卡）时没有 `system_id` 可查，
    这里回落到内置 COC7——这是当前唯一内置的规则系统，默认值刻意放在这层
    组装代码里，而不是塞进 `coc7_rules.py`：规则核心保持对具体系统无知，
    正是 issue #112 参数注入的整个目的。

    走 `require_ruleset` 而不是 `get_ruleset`：这是裁决路径，规则数据为空时
    必须拒绝而不是当成"零个约束"放行（见 `require_ruleset` 的说明）。
    """
    if room.system_id is not None:
        return await require_ruleset(db, room.system_id)
    return build_coc7_ruleset()


async def complete_character(
    db: AsyncSession, room_id: str, character_id: str, reconnect_token: str | None
) -> None:
    """标记建卡完成，并在同一事务中保存一份当前用户的可复用角色卡。

    issue #84 S2：落库前先用 `coc7_rules.validate_character` 权威校验已保存的
    属性/职业/技能是否合法，不合法直接抛 `CharacterInvalidError` 拒绝——
    `occupation` 字段存的是职业名字符串（不是 id，见 `Character` 模型注释），
    按名字映射回职业定义；映射不到时 `validate_character` 会产出
    `OCCUPATION_NOT_FOUND` 校验项，同样会被拒绝，不会静默放行。
    """
    character = await _get_own_character(db, room_id, character_id, reconnect_token)
    room = await find_room_by_id(db, room_id)
    _require_character_editable(room)
    ruleset = await _resolve_ruleset(db, room)
    issues = validate_age(ruleset, character.age) + validate_character(
        ruleset,
        attributes=character.attributes or {},
        occupation_name=character.occupation,
        skills=character.skills or {},
        occupation_choice_skill_ids=character.occupation_choice_skill_ids,
        generation_method=character.generation_method,
    )
    if issues:
        raise CharacterInvalidError(issues)

    # PR #85 review #3：校验通过后属性一定合法，衍生值改成服务端权威重算
    # 并覆盖——不再信任客户端 PATCH 上来的 `derived_stats`，避免属性合法但
    # HP/SAN 被客户端乱填过关。
    try:
        character.derived_stats = compute_derived_stats(character.attributes or {})
        character.status = "complete"
        character.version += 1
        player = await db.get(Player, character.player_id)
        if player is not None:
            player.has_character = True
        # 这里曾经隐式写一张用户卡（#121）。#337 去掉了：玩家从来看不到也删不掉
        # 它，而「改一笔再完成一次」就会再存一条，卡库只进不出。卡库现在只由
        # `POST /me/character-templates` 显式产生。
        await db.commit()
    except Exception:
        await db.rollback()
        raise


async def get_character(
    db: AsyncSession, room_id: str, character_id: str, reconnect_token: str | None
) -> CharacterRead:
    """GET /rooms/{roomId}/characters/{characterId} —— 读回自己的角色卡
    （issue #96）。

    鉴权复用 `_get_own_character`：只能读自己那张，不能拿别人的角色卡——
    角色卡里有背景故事、装备这些属于该玩家的信息，房间内其他人不该直接拉到。
    """
    character = await _get_own_character(db, room_id, character_id, reconnect_token)
    return CharacterRead(
        id=character.id,
        status=character.status,
        generation_method=character.generation_method,
        name=character.name,
        age=character.age,
        gender=character.gender,
        residence=character.residence or "",
        birthplace=character.birthplace or "",
        attributes=character.attributes or {},
        derived_stats=character.derived_stats or {},
        skills=character.skills or {},
        occupation_choice_skill_ids=character.occupation_choice_skill_ids,
        equipment=list(character.equipment or []),
        occupation=character.occupation,
        background=character.background or "",
        notes=character.notes or "",
    )


def compute_character_preview(
    ruleset: RulesetRead, payload: CharacterPreviewRequest
) -> CharacterComputeResult:
    """POST /api/v1/systems/{systemId}/character/preview —— 建卡过程中的权威
    计算预览（issue #84 S2，路线乙的接缝）：不碰数据库，纯函数式地把
    `coc7_rules.compute_preview` 的结果转成 DTO。

    `ruleset` 由调用方（controller）取好传入（issue #112）——它已经为了校验
    systemId 存在而查过一次 `get_ruleset`，这里直接复用结果，不重新查一次。
    """
    result = compute_preview(
        ruleset,
        attributes=payload.attributes,
        occupation_id=payload.occupation_id,
        skills=payload.skills,
        occupation_choice_skill_ids=payload.occupation_choice_skill_ids,
        generation_method=payload.generation_method,
    )
    return CharacterComputeResult(**asdict(result))


def _roll(n: int, sides: int) -> int:
    return sum(random.randint(1, sides) for _ in range(n))


async def roll_attributes(
    db: AsyncSession, room_id: str, character_id: str, reconnect_token: str | None
) -> RollAttributesResult:
    """POST /rooms/{roomId}/characters/{characterId}/roll-attributes —— 服务端
    权威掷骰生成属性（issue #77 新增，取代前端 `Math.random()` 本地算骰值）。

    COC7 标准生成法：STR/CON/DEX/APP/POW/LUCK = 3d6*5，SIZ/INT/EDU = (2d6+6)*5；
    幸运（LUCK）独立掷骰、不由属性推导，也不参与技能点公式，但它是游戏中可被
    消耗的有状态属性，所以跟其余 8 项一起放在 `attributes` 里而非衍生值；
    衍生值按标准公式：HP = (CON+SIZ)/10 取整，MP = POW/5 取整，SAN = POW*5
    （起始理智等于 POW 的 5 倍，跟 POW 属性值本身相等，这里遵循 COC7 规则
    直接抄一份 POW*5 = 属性打点后的数值）。

    注意这跟"三处原型取舍"表格里的 `check.*`（游戏中的技能/理智检定）是两回事：
    这里是建卡阶段生成初始属性的纯随机数生成，不涉及规则引擎裁决，本期就是
    真实实现，不是 NOT_IMPLEMENTED 桩。
    """
    character = await _get_own_character(db, room_id, character_id, reconnect_token)
    room = await find_room_by_id(db, room_id)
    _require_character_editable(room)
    await _mark_character_modified(db, character)

    attributes = {
        "STR": _roll(3, 6) * 5,
        "CON": _roll(3, 6) * 5,
        "DEX": _roll(3, 6) * 5,
        "APP": _roll(3, 6) * 5,
        "POW": _roll(3, 6) * 5,
        "SIZ": (_roll(2, 6) + 6) * 5,
        "INT": (_roll(2, 6) + 6) * 5,
        "EDU": (_roll(2, 6) + 6) * 5,
        "LUCK": _roll(3, 6) * 5,
    }
    derived_stats = {
        "HP": (attributes["CON"] + attributes["SIZ"]) // 10,
        "MP": attributes["POW"] // 5,
        "SAN": attributes["POW"],
    }

    character.attributes = attributes
    character.derived_stats = derived_stats
    # 标记这张卡的属性是掷出来的：complete 时不能拿点数购买法的总预算去卡它
    # （8 项总和均值约 457、范围 195–720，经常超 480）。见 issue #96 决策 1。
    character.generation_method = GENERATION_ROLL
    character.version += 1
    await db.commit()
    return RollAttributesResult(attributes=attributes, derived_stats=derived_stats)


async def quick_generate_character(
    db: AsyncSession,
    room_id: str,
    character_id: str,
    reconnect_token: str | None,
    background_service: CharacterBackgroundService | None = None,
    identity: QuickGenerateRequest | None = None,
) -> QuickGenerateResult:
    """生成并保存一张角色草稿，不标记完成，也不触发生图。"""
    character = await _get_own_character(db, room_id, character_id, reconnect_token)
    room = await find_room_by_id(db, room_id)
    _require_character_editable(room)
    ruleset = await _resolve_ruleset(db, room)
    generated = generate_character_draft(ruleset)
    if identity is not None:
        generated = replace(
            generated,
            name=(
                identity.name.strip() if identity.name and identity.name.strip() else generated.name
            ),
            age=identity.age if identity.age is not None else generated.age,
            gender=identity.gender or generated.gender,
            residence=identity.residence or generated.residence,
            birthplace=identity.birthplace or generated.birthplace,
        )

    if background_service is not None:
        occupation = next(
            (item for item in ruleset.occupations if item.id == generated.occupation_id), None
        )
        skill_specs = {skill.id: skill for skill in ruleset.skills}
        prominent_skills = [
            CharacterBackgroundSkill(
                id=skill_id,
                name=skill_specs[skill_id].name,
                value=value,
            )
            for skill_id, value in sorted(
                generated.skills.items(), key=lambda item: item[1], reverse=True
            )
            if skill_id in skill_specs
        ][:5]
        context = CharacterBackgroundContext(
            name=generated.name,
            age=generated.age,
            gender=generated.gender,
            residence=generated.residence,
            birthplace=generated.birthplace,
            occupation=generated.occupation,
            occupation_description=occupation.description if occupation else "",
            occupation_categories=occupation.categories if occupation else [],
            attributes=generated.attributes,
            prominent_skills=prominent_skills,
            credit_rating=generated.skills.get("credit-rating", 0),
            equipment=generated.equipment,
        )
        generation = await background_service.generate(
            context,
            fallback=generated.background,
            fallback_equipment=generated.equipment,
        )
        generated = replace(
            generated,
            background=generation.background,
            equipment=generation.equipment,
        )

    await _mark_character_modified(db, character)
    character.name = generated.name
    character.age = generated.age
    character.gender = generated.gender
    character.residence = generated.residence
    character.birthplace = generated.birthplace
    character.attributes = generated.attributes
    character.derived_stats = generated.derived_stats
    character.skills = generated.skills
    character.occupation_choice_skill_ids = generated.occupation_choice_skill_ids
    character.equipment = generated.equipment
    character.occupation = generated.occupation
    character.background = generated.background
    character.notes = generated.notes
    character.generation_method = "roll"
    character.version += 1
    try:
        await db.commit()
    except Exception:
        await db.rollback()
        raise

    return QuickGenerateResult(
        character=CharacterRead(
            id=character.id,
            status=character.status,
            generation_method=character.generation_method,
            name=character.name,
            age=character.age,
            gender=character.gender,
            residence=character.residence or "",
            birthplace=character.birthplace or "",
            attributes=character.attributes or {},
            derived_stats=character.derived_stats or {},
            skills=character.skills or {},
            occupation_choice_skill_ids=character.occupation_choice_skill_ids,
            equipment=list(character.equipment or []),
            occupation=character.occupation,
            background=character.background or "",
            notes=character.notes or "",
        ),
        occupation_id=generated.occupation_id,
        compute=CharacterComputeResult(**asdict(generated.compute_result)),
    )


# ── 我的常用角色卡库（#337：卡库卡是第一等实体，房间角色卡是它的一份拷贝） ──


def _template_read(template: UserCharacterTemplate) -> CharacterTemplateRead:
    return CharacterTemplateRead(
        template_id=template.id,
        name=template.name,
        system_id=template.system_id,
        data=dict(template.data or {}),
        created_at=template.created_at,
        updated_at=template.updated_at,
    )


def _data_with_attested_generation_method(
    stored: dict[str, object], incoming: dict[str, object]
) -> dict[str, object]:
    """`generation_method` 只能由服务端背书，客户端改不动它。

    「属性是掷出来的」这条声明的唯一作用，是让 `complete` 跳过点数购买法的总预算
    校验（掷骰结果经常超 480）。所以它必须来自服务端自己掷的那一次，否则客户端
    写上 roll 就能让 8 项全 90 过关。

    保留 roll 的唯一条件是这次写入**没有改动属性**——玩家改的是姓名、背景、技能
    分配这些。一旦属性变了，就说明属性不再是服务端掷出来的那一份，退回点数购买法。
    这跟房间版 `update_character` 里那道闸是同一个判据。
    """
    attested = stored.get("generation_method") == GENERATION_ROLL and incoming.get(
        "attributes"
    ) == stored.get("attributes")
    return {
        **incoming,
        "generation_method": GENERATION_ROLL if attested else GENERATION_POINT_BUY,
    }


async def _own_template(db: AsyncSession, user_id: str, template_id: str) -> UserCharacterTemplate:
    """按 (id, user_id) 取卡；别人的卡一律当作不存在。

    刻意不分「不存在」和「不是你的」：两者返回同一个 404，否则拿别人的
    templateId 试一遍就能问出「这张卡存在」。
    """
    template = await db.scalar(
        select(UserCharacterTemplate).where(
            UserCharacterTemplate.id == template_id,
            UserCharacterTemplate.user_id == user_id,
        )
    )
    if template is None:
        raise CharacterNotFoundError("角色卡不存在")
    return template


async def list_character_templates(
    db: AsyncSession, user_id: str, system_id: str | None = None
) -> list[CharacterTemplateRead]:
    """我的卡库列表，最近更新的在前。

    `system_id` 过滤给车卡界面用：COC7 的卡不该出现在别的规则系统的房间里，
    表结构本来就按 system 约束死了这张卡能用在哪。
    """
    statement = select(UserCharacterTemplate).where(UserCharacterTemplate.user_id == user_id)
    if system_id is not None:
        statement = statement.where(UserCharacterTemplate.system_id == system_id)
    rows = await db.scalars(statement.order_by(UserCharacterTemplate.updated_at.desc()))
    return [_template_read(template) for template in rows]


async def create_character_template(
    db: AsyncSession, user_id: str, payload: CharacterTemplateCreateBody
) -> CharacterTemplateRead:
    """显式保存一张卡库卡。

    落库前把 `generation_method` 压成点数购买法：客户端提交的数据里那个字段没有
    任何背书价值，而它恰好是 `complete` 用来跳过点数预算校验的开关。

    `system_id` 也要先确认存在。它是指向 `game_systems` 的外键，而本地和测试跑的
    SQLite 关着外键约束、随便写什么都能落库；线上 PostgreSQL 会在 commit 那一刻
    抛 IntegrityError，表现成 500。校验放在这里，两种方言都给同一个 404。
    """
    if await db.get(GameSystem, payload.system_id) is None:
        raise CharacterNotFoundError("规则系统不存在")
    _require_seedable_lengths(payload.data)
    template = UserCharacterTemplate(
        user_id=user_id,
        system_id=payload.system_id,
        name=payload.name,
        data={**dict(payload.data), "generation_method": GENERATION_POINT_BUY},
    )
    db.add(template)
    await db.commit()
    return _template_read(template)


async def get_character_template(
    db: AsyncSession, user_id: str, template_id: str
) -> CharacterTemplateRead:
    return _template_read(await _own_template(db, user_id, template_id))


async def update_character_template(
    db: AsyncSession, user_id: str, template_id: str, payload: CharacterTemplateUpdateBody
) -> CharacterTemplateRead:
    """改名或整体覆盖卡库卡的建卡态数据。

    卡库现在也是建卡的宿主（#337 决策 A），建卡向导的每一次保存都落到这里，
    所以 `data` 是整体覆盖而不是合并——合并语义下前端删掉一项技能就永远删不掉。
    """
    template = await _own_template(db, user_id, template_id)
    if payload.name is not None:
        template.name = payload.name
    if payload.data is not None:
        _require_seedable_lengths(payload.data)
        template.data = _data_with_attested_generation_method(
            dict(template.data or {}), dict(payload.data)
        )
    await db.commit()
    return _template_read(template)


async def delete_character_template(db: AsyncSession, user_id: str, template_id: str) -> None:
    """删除一张卡库卡，并把引用过它的房间角色卡的出处置空。

    置空是在这里显式做的，没有依赖数据库的 `ON DELETE SET NULL`：本地和全部
    测试跑的 SQLite `PRAGMA foreign_keys = 0`，外键根本不生效，而线上 PostgreSQL
    上这个 FK 是 `NO ACTION`——同一段代码两种行为（SQLite 静默留下悬空指针，
    PostgreSQL 直接 IntegrityError）。放在数据库层的话，测试里那条约束永远不会
    触发，等于写了个测不到的保证。

    房间角色卡本身不受影响：它在播种那一刻就把数据拷走了，是自足的，丢掉的只是
    「这张卡当初从哪来」这条出处信息。
    """
    template = await _own_template(db, user_id, template_id)
    await db.execute(
        update(Character)
        .where(Character.based_on_template_id == template_id)
        .values(based_on_template_id=None)
    )
    await db.delete(template)
    await db.commit()


# ── 不依赖房间的建卡（#337 决策 A：卡库也是建卡宿主） ──
#
# 这两个端点挂在卡库卡下面而不是 `/systems/{id}` 下，是因为「属性是掷出来的」
# 必须由服务端写进那张卡才算数。做成无状态、把点数交回客户端再让它自己 PATCH
# 的话，服务端就无从区分「这是我掷的」和「客户端自己填的」——而这正是
# `complete` 跳过点数预算校验的依据。


async def roll_template_attributes(
    db: AsyncSession, user_id: str, template_id: str
) -> RollAttributesResult:
    """服务端权威掷属性，直接写进这张卡库卡并背书为 roll。"""
    template = await _own_template(db, user_id, template_id)
    attributes = {
        "STR": _roll(3, 6) * 5,
        "CON": _roll(3, 6) * 5,
        "DEX": _roll(3, 6) * 5,
        "APP": _roll(3, 6) * 5,
        "POW": _roll(3, 6) * 5,
        "SIZ": (_roll(2, 6) + 6) * 5,
        "INT": (_roll(2, 6) + 6) * 5,
        "EDU": (_roll(2, 6) + 6) * 5,
        "LUCK": _roll(3, 6) * 5,
    }
    template.data = {
        **dict(template.data or {}),
        "attributes": attributes,
        "generation_method": GENERATION_ROLL,
    }
    await db.commit()
    return RollAttributesResult(
        attributes=attributes,
        derived_stats={
            "HP": (attributes["CON"] + attributes["SIZ"]) // 10,
            "MP": attributes["POW"] // 5,
            "SAN": attributes["POW"],
        },
    )


async def quick_generate_template(
    db: AsyncSession,
    user_id: str,
    template_id: str,
    ruleset: RulesetRead,
    identity: QuickGenerateRequest | None = None,
) -> SystemQuickGenerateResult:
    """一键生成一整份建卡态数据，写进这张卡库卡。

    不生成 AI 背景故事：房间版那条链路会调模型，而卡库建卡是玩家在自己账号下
    随手捏卡，不该每点一次就产生一次计费请求。想要生成的背景，进房建卡时再要。
    """
    template = await _own_template(db, user_id, template_id)
    generated = generate_character_draft(ruleset)
    if identity is not None:
        generated = replace(
            generated,
            name=(
                identity.name.strip() if identity.name and identity.name.strip() else generated.name
            ),
            age=identity.age if identity.age is not None else generated.age,
            gender=identity.gender or generated.gender,
            residence=identity.residence or generated.residence,
            birthplace=identity.birthplace or generated.birthplace,
        )
    data: dict[str, object] = {
        "generation_method": GENERATION_ROLL,
        "name": generated.name,
        "age": generated.age,
        "gender": generated.gender,
        "residence": generated.residence,
        "birthplace": generated.birthplace,
        "attributes": dict(generated.attributes),
        "skills": dict(generated.skills),
        "occupation_choice_skill_ids": list(generated.occupation_choice_skill_ids),
        "equipment": list(generated.equipment),
        "occupation": generated.occupation,
        "background": generated.background,
        "notes": generated.notes,
    }
    template.data = data
    # 卡库列表展示的是顶层 name，不是 data.name。只更新后者的话，玩家一键生成出
    # 「叶探员」，列表里还挂着建卡时那个占位名。
    template.name = generated.name
    await db.commit()
    return SystemQuickGenerateResult(
        data=data,
        occupation_id=generated.occupation_id,
        compute=CharacterComputeResult(**asdict(generated.compute_result)),
    )
