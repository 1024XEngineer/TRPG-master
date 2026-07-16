"""Service 层：角色（调查员）建卡（issue #59，issue #77 切换为真实 ORM 读写
+ 补齐服务端权威掷骰 / 角色卡模板两个新协议位置）。

建卡流程分两段：POST 创建草稿 → PATCH 保存完整数据 → POST complete 标记完成。
房间/重连凭证校验复用 service/room.py 的 `get_player_by_reconnect_token`——
角色卡操作跟房间操作共用同一套"这是房间里的哪个玩家"身份体系。
"""

import random

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_implemented
from app.dto.character import (
    CharacterDraftResult,
    CharacterTemplateCreateBody,
    CharacterTemplateRead,
    CharacterUpdateBody,
    RollAttributesResult,
)
from app.models.room import Character, Player
from app.service.room import (
    RoomAuthorizationError,
    find_room_by_id,
    get_player_by_reconnect_token,
)


class CharacterNotFoundError(ValueError):
    """角色不存在。"""


async def create_character_draft(
    db: AsyncSession, room_id: str, reconnect_token: str | None, based_on_template_id: str | None
) -> CharacterDraftResult:
    """房间内玩家创建一份角色草稿。

    `based_on_template_id`（issue #77 新增第三条建卡路径，issue 决策 5）：
    带了这个字段说明玩家想复用自己的常用卡，但"复制模板数据进草稿"这条读写
    本期没有实现（决策 5 原文：本期只铺表与接口，不实现），直接 NOT_IMPLEMENTED，
    不创建任何草稿；不带这个字段则完全是原来"从零建卡"的行为，不受影响。
    """
    if based_on_template_id is not None:
        raise not_implemented("复用常用角色卡本期尚未实现")

    room = await find_room_by_id(db, room_id)
    player = await get_player_by_reconnect_token(db, reconnect_token)
    if player.room_id != room.id:
        raise RoomAuthorizationError("你不在这个房间里")

    character = Character(room_id=room_id, player_id=player.id, status="draft")
    db.add(character)
    await db.commit()
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
    character.name = payload.name
    character.attributes = payload.attributes
    character.derived_stats = payload.derived_stats
    character.skills = payload.skills
    character.equipment = [item.name for item in payload.equipment]
    character.occupation = payload.occupation
    character.background = payload.background
    character.notes = payload.notes
    await db.commit()


async def complete_character(
    db: AsyncSession, room_id: str, character_id: str, reconnect_token: str | None
) -> None:
    """标记建卡完成，同步把对应玩家的 has_character 置为 True。"""
    character = await _get_own_character(db, room_id, character_id, reconnect_token)
    character.status = "complete"
    player = await db.get(Player, character.player_id)
    if player is not None:
        player.has_character = True
    await db.commit()


def _roll(n: int, sides: int) -> int:
    return sum(random.randint(1, sides) for _ in range(n))


async def roll_attributes(
    db: AsyncSession, room_id: str, character_id: str, reconnect_token: str | None
) -> RollAttributesResult:
    """POST /rooms/{roomId}/characters/{characterId}/roll-attributes —— 服务端
    权威掷骰生成属性（issue #77 新增，取代前端 `Math.random()` 本地算骰值）。

    COC7 标准生成法：STR/CON/DEX/APP/POW = 3d6*5，SIZ/INT/EDU = (2d6+6)*5；
    衍生值按标准公式：HP = (CON+SIZ)/10 取整，MP = POW/5 取整，SAN = POW*5
    （起始理智等于 POW 的 5 倍，跟 POW 属性值本身相等，这里遵循 COC7 规则
    直接抄一份 POW*5 = 属性打点后的数值）。

    注意这跟"三处原型取舍"表格里的 `check.*`（游戏中的技能/理智检定）是两回事：
    这里是建卡阶段生成初始属性的纯随机数生成，不涉及规则引擎裁决，本期就是
    真实实现，不是 NOT_IMPLEMENTED 桩。
    """
    character = await _get_own_character(db, room_id, character_id, reconnect_token)

    attributes = {
        "STR": _roll(3, 6) * 5,
        "CON": _roll(3, 6) * 5,
        "DEX": _roll(3, 6) * 5,
        "APP": _roll(3, 6) * 5,
        "POW": _roll(3, 6) * 5,
        "SIZ": (_roll(2, 6) + 6) * 5,
        "INT": (_roll(2, 6) + 6) * 5,
        "EDU": (_roll(2, 6) + 6) * 5,
    }
    derived_stats = {
        "HP": (attributes["CON"] + attributes["SIZ"]) // 10,
        "MP": attributes["POW"] // 5,
        "SAN": attributes["POW"],
    }

    character.attributes = attributes
    character.derived_stats = derived_stats
    await db.commit()
    return RollAttributesResult(attributes=attributes, derived_stats=derived_stats)


# ── 我的常用角色卡库（issue 决策 5：本期只铺表与接口，不实现真实读写） ──


async def list_character_templates(db: AsyncSession, user_id: str) -> list[CharacterTemplateRead]:
    raise not_implemented("我的常用角色卡库本期尚未实现")


async def create_character_template(
    db: AsyncSession, user_id: str, payload: CharacterTemplateCreateBody
) -> CharacterTemplateRead:
    raise not_implemented("我的常用角色卡库本期尚未实现")


async def get_character_template(
    db: AsyncSession, user_id: str, template_id: str
) -> CharacterTemplateRead:
    raise not_implemented("我的常用角色卡库本期尚未实现")


async def delete_character_template(db: AsyncSession, user_id: str, template_id: str) -> None:
    raise not_implemented("我的常用角色卡库本期尚未实现")
