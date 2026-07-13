"""大厅浏览与创建房间 —— 对应 API 对齐规范 §2.1/§2.2。"""

from __future__ import annotations

import secrets
import string
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from server.rest.schema import CamelModel
from sqlalchemy import func, select

from core.content.db_models import ModulePackRow
from core.db import get_sessionmaker
from core.state.db_models import PlayerRow, RoomRow, UserRow
from server.rest.deps import get_current_user

router = APIRouter(tags=["lobby"])

# ★ 2026-07-13：本次不做模组导入，游戏/规则系统目录先硬编码——只有一款真正
# 落库的模组（惠特利旧宅，见 scripts/seed_demo_module.py），够 /goal 这次
# "自己模拟一个 COC 模组"的范围用。


class GameSummary(CamelModel):
    id: str
    name: str
    icon: str
    status: str


@router.get("/games")
async def list_games() -> list[GameSummary]:
    """不需要登录，相当于逛 demo。"""
    return [GameSummary(id="trpg", name="跑团", icon="scroll-text", status="ready")]


class SystemSummary(CamelModel):
    id: str
    game_id: str
    name: str
    status: str


@router.get("/games/{game_id}/systems")
async def list_systems(game_id: str) -> list[SystemSummary]:
    if game_id != "trpg":
        return []
    return [SystemSummary(id="coc", game_id="trpg", name="克苏鲁的呼唤 7th", status="ready")]


_ROOM_CODE_ALPHABET = "".join(c for c in string.ascii_uppercase + string.digits if c not in "0O1I")


def _generate_room_code() -> str:
    return "".join(secrets.choice(_ROOM_CODE_ALPHABET) for _ in range(6))


class CreateRoomRequest(CamelModel):
    nickname: Optional[str] = None


class CreateRoomResponse(CamelModel):
    room_id: str
    room_code: str
    reconnect_token: str
    player_id: str  # 房主创建即加入（见 §5.2.5），前端后续建卡/WS room.join 都需要这个 id


@router.post("/rooms", status_code=201)
async def create_room(body: CreateRoomRequest, user: UserRow = Depends(get_current_user)) -> CreateRoomResponse:
    """🔒 需登录。此时 game_id/system_id/scenario_id 全部为空——选游戏/选系统是
    房主单人操作、纯前端导航不落后端。房主创建即加入，同时建一条 PlayerRow。
    module_pack_id 在这一步先指向唯一的内置模组，select_module 会再确认一次
    （本次没有多模组可选，但保留这个两步流程以对齐设计文档）。
    """
    room_id = f"room_{uuid.uuid4().hex[:12]}"
    player_id = f"player_{uuid.uuid4().hex[:12]}"
    reconnect_token = f"rtok_{secrets.token_urlsafe(24)}"

    async with get_sessionmaker()() as session:
        default_module = (
            await session.execute(select(ModulePackRow).limit(1))
        ).scalars().first()
        if default_module is None:
            raise HTTPException(status_code=500, detail="没有可用的模组，请先跑 scripts/seed_demo_module.py")

        room_code = _generate_room_code()
        session.add(
            RoomRow(
                id=room_id,
                room_code=room_code,
                host_player_id=player_id,
                host_user_id=user.id,
                module_pack_id=default_module.id,
                phase="Lobby",
                entity_states={},
                rolling_summary=None,
            )
        )
        await session.flush()

        session.add(
            PlayerRow(
                id=player_id,
                room_id=room_id,
                nickname=body.nickname or user.nickname,
                character_id=None,
                user_id=user.id,
                ready=False,
                connected=False,
                reconnect_token=reconnect_token,
            )
        )
        await session.commit()

    return CreateRoomResponse(room_id=room_id, room_code=room_code, reconnect_token=reconnect_token, player_id=player_id)


@router.post("/rooms/{room_code}/join")
async def join_room(
    room_code: str, body: CreateRoomRequest, user: UserRow = Depends(get_current_user)
) -> CreateRoomResponse:
    """🔒 需登录。访客用房间码加入——找不到房间 404；已经是本房间玩家（重复
    加入/断线重连）幂等返回已有身份；否则新建一条 PlayerRow。"""
    async with get_sessionmaker()() as session:
        room = (
            await session.execute(select(RoomRow).where(RoomRow.room_code == room_code))
        ).scalar_one_or_none()
        if room is None:
            raise HTTPException(status_code=404, detail="房间不存在")

        existing = (
            await session.execute(
                select(PlayerRow).where(PlayerRow.room_id == room.id, PlayerRow.user_id == user.id)
            )
        ).scalar_one_or_none()
        if existing is not None:
            return CreateRoomResponse(
                room_id=room.id,
                room_code=room.room_code,
                reconnect_token=existing.reconnect_token,
                player_id=existing.id,
            )

        player_id = f"player_{uuid.uuid4().hex[:12]}"
        reconnect_token = f"rtok_{secrets.token_urlsafe(24)}"
        session.add(
            PlayerRow(
                id=player_id,
                room_id=room.id,
                nickname=body.nickname or user.nickname,
                character_id=None,
                user_id=user.id,
                ready=False,
                connected=False,
                reconnect_token=reconnect_token,
            )
        )
        await session.commit()

    return CreateRoomResponse(
        room_id=room.id, room_code=room.room_code, reconnect_token=reconnect_token, player_id=player_id
    )


class RoomPreview(CamelModel):
    room_id: str
    room_code: str
    phase: str
    module_title: Optional[str]
    player_count: int
    max_players: int


@router.get("/rooms/{room_code}")
async def preview_room(room_code: str) -> RoomPreview:
    """不强制登录——供加入前预览。"""
    async with get_sessionmaker()() as session:
        room = (
            await session.execute(select(RoomRow).where(RoomRow.room_code == room_code))
        ).scalar_one_or_none()
        if room is None:
            raise HTTPException(status_code=404, detail="房间不存在")

        module = await session.get(ModulePackRow, room.module_pack_id)
        player_count = (
            await session.execute(select(func.count()).select_from(PlayerRow).where(PlayerRow.room_id == room.id))
        ).scalar_one()

        return RoomPreview(
            room_id=room.id,
            room_code=room.room_code,
            phase=room.phase,
            module_title=module.title if module else None,
            player_count=player_count,
            max_players=module.players_max if module else 1,
        )


class SelectModuleRequest(CamelModel):
    module_id: str
    attribute_gen_method: str = "point_buy"


@router.post("/rooms/{room_id}/module")
async def select_module(
    room_id: str, body: SelectModuleRequest, user: UserRow = Depends(get_current_user)
) -> dict:
    """🔒 需登录仅房主。幂等条件更新（WHERE scenario_id IS NULL）防竞态；
    已设置过返回 409 MODULE_ALREADY_SELECTED。这个端点也是导入失败后房主
    改选内置模组救场复用的同一入口。"""
    async with get_sessionmaker()() as session:
        room = await session.get(RoomRow, room_id)
        if room is None:
            raise HTTPException(status_code=404, detail="房间不存在")
        if room.host_user_id != user.id:
            raise HTTPException(status_code=403, detail="仅房主可选择模组")
        if room.phase != "Lobby":
            raise HTTPException(status_code=409, detail="MODULE_ALREADY_SELECTED")

        module = await session.get(ModulePackRow, body.module_id)
        if module is None:
            raise HTTPException(status_code=404, detail="模组不存在")

        room.module_pack_id = body.module_id
        room.phase = "ModuleSelected"
        await session.commit()

        return {"roomId": room_id, "phase": room.phase, "moduleId": body.module_id}
