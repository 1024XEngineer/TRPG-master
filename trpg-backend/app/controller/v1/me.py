"""Controller 层：`/api/v1/me` 路由 —— 当前用户相关接口（issue #77 补充"我的
常用角色卡库" 4 个端点，本期均为 NOT_IMPLEMENTED 桩，见 issue 决策 5）。
"""

from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.controller.dependencies import extract_bearer_token
from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.character import CharacterTemplateCreateBody, CharacterTemplateRead
from app.dto.common import ApiResponse
from app.dto.room import MyRoomSummary
from app.service import auth as auth_service
from app.service import character as character_service
from app.service import room as room_service

router = APIRouter(prefix="/me", tags=["me"])


@router.get("/rooms", response_model=ApiResponse[list[MyRoomSummary]])
async def list_my_rooms(
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[MyRoomSummary]]:
    """GET /api/v1/me/rooms —— 获取我的房间列表。"""
    try:
        rooms = await room_service.list_my_rooms(db, reconnect_token)
    except room_service.RoomAuthenticationError as exc:
        raise AppException(ErrorCode.UNAUTHORIZED, str(exc), status.HTTP_401_UNAUTHORIZED) from exc
    return ApiResponse.ok(rooms)


async def _require_user_id(authorization: str | None, db: AsyncSession) -> str:
    try:
        me = await auth_service.get_me(db, extract_bearer_token(authorization))
    except auth_service.AuthenticationError as exc:
        raise AppException(ErrorCode.UNAUTHORIZED, str(exc), status.HTTP_401_UNAUTHORIZED) from exc
    return me.user_id


@router.get("/character-templates", response_model=ApiResponse[list[CharacterTemplateRead]])
async def list_character_templates(
    authorization: str | None = Header(default=None), db: AsyncSession = Depends(get_db)
) -> ApiResponse[list[CharacterTemplateRead]]:
    """GET /api/v1/me/character-templates —— 我的卡库列表（issue 决策 5，本期未实现）。"""
    user_id = await _require_user_id(authorization, db)
    templates = await character_service.list_character_templates(db, user_id)
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
    """POST /api/v1/me/character-templates —— 把一张角色卡保存为常用卡（本期未实现）。"""
    user_id = await _require_user_id(authorization, db)
    template = await character_service.create_character_template(db, user_id, payload)
    return ApiResponse.ok(template)


@router.get("/character-templates/{template_id}", response_model=ApiResponse[CharacterTemplateRead])
async def get_character_template(
    template_id: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CharacterTemplateRead]:
    """GET /api/v1/me/character-templates/{templateId} —— 卡库详情（本期未实现）。"""
    user_id = await _require_user_id(authorization, db)
    template = await character_service.get_character_template(db, user_id, template_id)
    return ApiResponse.ok(template)


@router.delete("/character-templates/{template_id}", response_model=ApiResponse[None])
async def delete_character_template(
    template_id: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """DELETE /api/v1/me/character-templates/{templateId} —— 删除常用卡（本期未实现）。"""
    user_id = await _require_user_id(authorization, db)
    await character_service.delete_character_template(db, user_id, template_id)
    return ApiResponse.ok(None)
