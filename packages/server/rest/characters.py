"""建卡 —— 对应 API 对齐规范 §2.6。

全局原则：服务端权威掷骰——不管是本模块的建卡属性掷骰，还是正式游玩阶段
的技能检定，骰子结果一律由服务端计算，客户端只展示、不自己算完再上报。

★ 2026-07-13 范围：本次只做"只有玩家能建卡"这一条（复盘/KP 相关不做）。
职业/技能数据沿用前端已有的真实 COC7 数据（`trpg-app/src/data/occupations.ts`，
已核对与 COC7空白卡CY23Final.xlsx 的信用评级/技能点公式一致），后端负责的是
把玩家在前端算好的属性/技能/职业信息真实落库，而不是重新实现一遍建卡规则表。
"""

from __future__ import annotations

import random
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from server.rest.schema import CamelModel
from sqlalchemy import select

from core.content.db_models import ModuleSceneRow
from core.db import get_sessionmaker
from core.state.db_models import CharacterRow, PlayerRow, RoomRow, UserRow
from server.rest.deps import get_current_user

router = APIRouter(tags=["characters"])

ATTRIBUTE_KEYS = ["STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU"]


@router.get("/systems/{system_id}/ruleset")
async def get_ruleset(system_id: str, user: UserRow = Depends(get_current_user)) -> dict:
    """🔒 需登录。一次性拉取建卡所需全部规则数据。★ 本次范围小：只给属性键位表，
    职业/技能目录沿用前端本地的真实 COC7 数据（见文件顶部说明），不重复维护两份。
    """
    return {
        "systemId": system_id,
        "attributes": ATTRIBUTE_KEYS,
        "attributeRange": {"min": 15, "max": 99},
        "attributeGenMethods": ["point_buy", "roll"],
    }


async def _get_player_for_character_action(session, room_id: str, user: UserRow) -> PlayerRow:
    """校验：只有玩家本人能建/改自己的角色卡（不是 KP，不是别的玩家）。"""
    result = await session.execute(
        select(PlayerRow).where(PlayerRow.room_id == room_id, PlayerRow.user_id == user.id)
    )
    player = result.scalar_one_or_none()
    if player is None:
        raise HTTPException(status_code=403, detail="你不是这个房间的玩家")
    return player


async def _pick_start_scene_id(session, module_id: str) -> str:
    rows = (await session.execute(select(ModuleSceneRow).where(ModuleSceneRow.module_id == module_id))).scalars().all()
    if not rows:
        raise HTTPException(status_code=500, detail="模组没有任何场景")
    preferred = next((s for s in rows if s.id == "scene-gate"), None)
    return (preferred or rows[0]).id


class CreateCharacterRequest(CamelModel):
    based_on_pregen_id: Optional[str] = None


@router.post("/rooms/{room_id}/characters", status_code=201)
async def create_character(
    room_id: str, body: CreateCharacterRequest, user: UserRow = Depends(get_current_user)
) -> dict:
    """两条创建路径：套用预设(basedOnPregenId)→status 直接 complete；
    从零建卡({})→status draft，走断点续建。服务端校验 phase>=ModuleSelected。
    ★ 本次没有 module_pregens 表/数据，basedOnPregenId 路径未实现，统一走 draft。
    """
    async with get_sessionmaker()() as session:
        room = await session.get(RoomRow, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="房间不存在")
        if room.phase == "Lobby":
            raise HTTPException(status_code=409, detail="MODULE_NOT_SELECTED")

        player = await _get_player_for_character_action(session, room_id, user)

        start_scene_id = await _pick_start_scene_id(session, room.module_pack_id)

        character_id = f"character_{uuid.uuid4().hex[:12]}"
        session.add(
            CharacterRow(
                id=character_id,
                room_id=room_id,
                player_id=player.id,
                based_on_pregen_id=None,
                name="",
                attributes={},
                derived_stats={},
                skills={},
                equipment=[],
                location=start_scene_id,
                conditions=[],
                ledger={},
                flags=[],
                status="draft",
            )
        )
        await session.commit()

        return {"characterId": character_id, "status": "draft"}


@router.patch("/rooms/{room_id}/characters/{character_id}")
async def patch_character(room_id: str, character_id: str, body: dict, user: UserRow = Depends(get_current_user)) -> dict:
    """草稿分步增量保存，覆盖式合并，status 保持 draft，不做强校验。

    接受的字段（camelCase，来自前端）：name / attributes / derivedStats / skills /
    equipment / occupation / background / notes（后两者暂存进 flags，本次没有
    单独的自由文本列，见 §8.1"物品不实体化"同一类简化）。
    """
    async with get_sessionmaker()() as session:
        await _get_player_for_character_action(session, room_id, user)
        character = await session.get(CharacterRow, character_id)
        if character is None or character.room_id != room_id:
            raise HTTPException(status_code=404, detail="角色不存在")

        if "name" in body:
            character.name = body["name"]
        if "attributes" in body:
            character.attributes = body["attributes"]
        if "derivedStats" in body:
            character.derived_stats = body["derivedStats"]
        if "skills" in body:
            character.skills = body["skills"]
        if "equipment" in body:
            character.equipment = body["equipment"]
        extra_notes = []
        if body.get("occupation"):
            extra_notes.append(f"职业：{body['occupation']}")
        if body.get("background"):
            extra_notes.append(f"背景：{body['background']}")
        if body.get("notes"):
            extra_notes.append(f"备注：{body['notes']}")
        if extra_notes:
            character.flags = extra_notes

        await session.commit()
        return {"characterId": character_id, "status": character.status}


@router.post("/rooms/{room_id}/characters/{character_id}/roll-attributes")
async def roll_attributes(room_id: str, character_id: str, user: UserRow = Depends(get_current_user)) -> dict:
    """attribute_gen_method='roll' 时用；point_buy 房间调用返回 400。
    服务端权威计算——不管前端展示成什么摇骰动画，真正的随机数在这里产生。
    COC7 经典生成法：STR/CON/DEX/APP/POW = 3D6×5，SIZ/INT/EDU = (2D6+6)×5。
    """
    async with get_sessionmaker()() as session:
        await _get_player_for_character_action(session, room_id, user)
        character = await session.get(CharacterRow, character_id)
        if character is None or character.room_id != room_id:
            raise HTTPException(status_code=404, detail="角色不存在")

        def roll_3d6x5() -> int:
            return sum(random.randint(1, 6) for _ in range(3)) * 5

        def roll_2d6_6x5() -> int:
            return (sum(random.randint(1, 6) for _ in range(2)) + 6) * 5

        attributes = {
            "STR": roll_3d6x5(),
            "CON": roll_3d6x5(),
            "DEX": roll_3d6x5(),
            "APP": roll_3d6x5(),
            "POW": roll_3d6x5(),
            "SIZ": roll_2d6_6x5(),
            "INT": roll_2d6_6x5(),
            "EDU": roll_2d6_6x5(),
        }
        character.attributes = attributes
        await session.commit()
        return {"characterId": character_id, "attributes": attributes}


@router.post("/rooms/{room_id}/characters/{character_id}/complete")
async def complete_character(room_id: str, character_id: str, user: UserRow = Depends(get_current_user)) -> dict:
    """触发完整校验，失败返回 422。★ 本次校验从简：只查姓名非空、属性齐全——
    职业点分配/信用评级区间等更细的规则校验留到后续里程碑（前端本地已经在做
    点数上限的 UI 层校验，这里只是最后一道后端兜底，不是本次实现重点）。
    """
    async with get_sessionmaker()() as session:
        player = await _get_player_for_character_action(session, room_id, user)
        character = await session.get(CharacterRow, character_id)
        if character is None or character.room_id != room_id:
            raise HTTPException(status_code=404, detail="角色不存在")

        errors = {}
        if not character.name:
            errors["name"] = "角色姓名不能为空"
        if not character.attributes or len(character.attributes) < len(ATTRIBUTE_KEYS):
            errors["attributes"] = "属性未填写完整"
        if errors:
            raise HTTPException(status_code=422, detail=errors)

        character.status = "complete"
        player.character_id = character.id
        await session.commit()

        return {"characterId": character_id, "status": "complete"}
