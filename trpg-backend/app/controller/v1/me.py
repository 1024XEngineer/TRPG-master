"""Controller 层：`/api/v1/me` 路由 —— 当前用户相关接口。

「我的常用角色卡库」在 #77 铺好协议位置、#337 落地实现：卡库卡是玩家自己的
第一等资产，房间角色卡是它的一份拷贝。
"""

from fastapi import APIRouter, Depends, Header, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.controller.dependencies import extract_bearer_token, get_current_user
from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.character import (
    CharacterTemplateCreateBody,
    CharacterTemplateRead,
    CharacterTemplateUpdateBody,
)
from app.dto.common import ApiResponse
from app.dto.room import MyRoomSummary
from app.models.user import User
from app.service import auth as auth_service
from app.service import character as character_service
from app.service import room as room_service

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/rooms", response_model=ApiResponse[list[MyRoomSummary]])
async def list_my_rooms(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse[list[MyRoomSummary]]:
    """GET /api/v1/me/rooms —— 获取我的房间列表。

    issue #106：凭证从房间的 `X-Reconnect-Token` 换成账号 `Authorization`。原来
    按重连凭证查，一个凭证只对应一名玩家/一个房间，「我的游戏」实际上是「这个
    浏览器的最后一个房间」——换台设备就什么都看不到，而账号体系当初正是为
    「换设备找回游戏」引入的。
    """
    rooms = await room_service.list_my_rooms(db, user)
    return ApiResponse.ok(rooms)


async def _require_user_id(authorization: str | None, db: AsyncSession) -> str:
    try:
        me = await auth_service.get_me(db, extract_bearer_token(authorization))
    except auth_service.AuthenticationError as exc:
        raise AppException(ErrorCode.UNAUTHORIZED, str(exc), status.HTTP_401_UNAUTHORIZED) from exc
    return me.user_id


def _not_found(exc: Exception) -> AppException:
    """卡库的「不存在」和「不是你的」共用 404（见 service 层 `_own_template`）。"""
    return AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND)


@router.get("/character-templates", response_model=ApiResponse[list[CharacterTemplateRead]])
async def list_character_templates(
    system_id: str | None = Query(default=None, alias="systemId", min_length=1),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[CharacterTemplateRead]]:
    """GET /api/v1/me/character-templates —— 我的卡库列表，最近更新的在前。

    `systemId` 给车卡界面用：只列出能用在这个规则系统的卡。
    """
    user_id = await _require_user_id(authorization, db)
    templates = await character_service.list_character_templates(db, user_id, system_id)
    return ApiResponse.ok(templates)


@router.post(
    "/character-templates",
    response_model=ApiResponse[CharacterTemplateRead],
    status_code=status.HTTP_201_CREATED,
)
async def create_character_template(
    payload: CharacterTemplateCreateBody,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CharacterTemplateRead]:
    """POST /api/v1/me/character-templates —— 把一张角色卡保存为常用卡。"""
    user_id = await _require_user_id(authorization, db)
    template = await character_service.create_character_template(db, user_id, payload)
    return ApiResponse.ok(template)


@router.get("/character-templates/{template_id}", response_model=ApiResponse[CharacterTemplateRead])
async def get_character_template(
    template_id: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CharacterTemplateRead]:
    """GET /api/v1/me/character-templates/{templateId} —— 卡库详情。"""
    user_id = await _require_user_id(authorization, db)
    try:
        template = await character_service.get_character_template(db, user_id, template_id)
    except character_service.CharacterNotFoundError as exc:
        raise _not_found(exc) from exc
    return ApiResponse.ok(template)


@router.patch(
    "/character-templates/{template_id}", response_model=ApiResponse[CharacterTemplateRead]
)
async def update_character_template(
    template_id: str,
    payload: CharacterTemplateUpdateBody,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CharacterTemplateRead]:
    """PATCH /api/v1/me/character-templates/{templateId} —— 改名或覆盖建卡态数据。

    卡库同时是建卡宿主（#337 决策 A），不依赖房间的建卡向导每一步都存到这里。
    """
    user_id = await _require_user_id(authorization, db)
    try:
        template = await character_service.update_character_template(
            db, user_id, template_id, payload
        )
    except character_service.CharacterNotFoundError as exc:
        raise _not_found(exc) from exc
    return ApiResponse.ok(template)


@router.delete("/character-templates/{template_id}", response_model=ApiResponse[None])
async def delete_character_template(
    template_id: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """DELETE /api/v1/me/character-templates/{templateId} —— 删除常用卡。

    引用过它的房间角色卡不受影响，只是出处被置空（见 service 层说明）。
    """
    user_id = await _require_user_id(authorization, db)
    try:
        await character_service.delete_character_template(db, user_id, template_id)
    except character_service.CharacterNotFoundError as exc:
        raise _not_found(exc) from exc
    return ApiResponse.ok(None)
