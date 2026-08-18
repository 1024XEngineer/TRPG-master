"""Controller 层：`/api/v1/me` 路由 —— 当前用户相关接口。

「我的常用角色卡库」在 #77 铺好协议位置、#337 落地实现：卡库卡是玩家自己的
第一等资产，房间角色卡是它的一份拷贝。
"""

from fastapi import APIRouter, Body, Depends, Header, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.controller.dependencies import extract_bearer_token, get_current_user
from app.core.coc7_character_generation import CharacterGenerationError
from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.character import (
    CharacterTemplateCreateBody,
    CharacterTemplateRead,
    CharacterTemplateUpdateBody,
    QuickGenerateRequest,
    RollAttributesResult,
    SystemQuickGenerateResult,
)
from app.dto.common import ApiResponse
from app.dto.game import RulesetRead
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


def _invalid_data(exc: Exception) -> AppException:
    return AppException(ErrorCode.VALIDATION_ERROR, str(exc), status.HTTP_422_UNPROCESSABLE_CONTENT)


def _duplicate(exc: character_service.CharacterTemplateDuplicateError) -> AppException:
    """内容重复不是"保存失败"，而是"它已经在库里了"（#337）。

    `details` 带上既有那张的 templateId，前端据此把"存卡"按钮指向它——玩家该看到
    的是「这张卡已经在卡库里了」，不是一句无从下手的错误。
    """
    return AppException(
        ErrorCode.CHARACTER_TEMPLATE_DUPLICATE,
        str(exc),
        status.HTTP_409_CONFLICT,
        details=[{"templateId": exc.template_id}],
    )


def _etag_matches(if_none_match: str | None, current_etag: str) -> bool:
    if not if_none_match:
        return False
    return any(
        candidate.strip() == "*" or candidate.strip().removeprefix("W/") == current_etag
        for candidate in if_none_match.split(",")
    )


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
    try:
        template = await character_service.create_character_template(db, user_id, payload)
    except character_service.CharacterNotFoundError as exc:
        raise _not_found(exc) from exc
    except character_service.CharacterInvalidDataError as exc:
        raise _invalid_data(exc) from exc
    except character_service.CharacterTemplateDuplicateError as exc:
        raise _duplicate(exc) from exc
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


@router.get("/character-templates/{template_id}/portrait", response_class=Response)
async def get_character_template_portrait(
    template_id: str,
    _version: str | None = Query(default=None, alias="v"),
    authorization: str | None = Header(default=None),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """GET /me/character-templates/{templateId}/portrait —— 鉴权读取模板头像。"""
    del _version  # 仅作为浏览器缓存分版参数，身份和内容均以后端存储为准。
    user_id = await _require_user_id(authorization, db)
    try:
        portrait = await character_service.get_character_template_portrait(db, user_id, template_id)
    except character_service.CharacterNotFoundError as exc:
        raise _not_found(exc) from exc
    etag = f'"{portrait.content_hash}"'
    cache_headers = {
        "ETag": etag,
        "Cache-Control": "private, max-age=3600",
        "X-Content-Type-Options": "nosniff",
    }
    if _etag_matches(if_none_match, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=cache_headers)
    return Response(
        content=portrait.content,
        media_type=portrait.content_type,
        headers={"Content-Length": str(portrait.size_bytes), **cache_headers},
    )


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
    except character_service.CharacterInvalidDataError as exc:
        raise _invalid_data(exc) from exc
    except character_service.CharacterTemplateDuplicateError as exc:
        raise _duplicate(exc) from exc
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


# ── 不依赖房间的建卡（#337 决策 A） ─────────────────────────────────────────
#
# 挂在卡库卡下面而不是 `/systems/{systemId}` 下：服务端必须**把掷骰结果写进那张
# 卡**，「属性是掷出来的」才算数。做成无状态、把点数交回客户端再让它自己 PATCH
# 的话，服务端无从区分「这是我掷的」和「客户端自己填的」——而这正是 `complete`
# 跳过点数预算校验的依据，客户端一旦能自称 roll，8 项全 90 也能过关。


async def _template_ruleset(
    db: AsyncSession, user_id: str, template_id: str
) -> tuple[str, RulesetRead]:
    """解析这张卡库卡所属规则系统的 ruleset，顺带确认卡是这个人的。"""
    template = await character_service.get_character_template(db, user_id, template_id)
    try:
        return template.template_id, await room_service.require_ruleset(db, template.system_id)
    except room_service.ModuleNotFoundError as exc:
        raise AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND) from exc
    except room_service.RulesetNotConfiguredError as exc:
        raise AppException(
            ErrorCode.RULESET_NOT_CONFIGURED, str(exc), status.HTTP_409_CONFLICT
        ) from exc


@router.post(
    "/character-templates/{template_id}/roll-attributes",
    response_model=ApiResponse[RollAttributesResult],
)
async def roll_template_attributes(
    template_id: str,
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RollAttributesResult]:
    """POST /api/v1/me/character-templates/{templateId}/roll-attributes。

    服务端权威掷骰，结果直接写进这张卡并背书为 roll。之后任何改动属性的 PATCH
    都会把这条背书退回点数购买法。
    """
    user_id = await _require_user_id(authorization, db)
    try:
        await _template_ruleset(db, user_id, template_id)
        result = await character_service.roll_template_attributes(db, user_id, template_id)
    except character_service.CharacterNotFoundError as exc:
        raise _not_found(exc) from exc
    except character_service.CharacterTemplateDuplicateError as exc:
        raise _duplicate(exc) from exc
    return ApiResponse.ok(result)


@router.post(
    "/character-templates/{template_id}/quick-generate",
    response_model=ApiResponse[SystemQuickGenerateResult],
)
async def quick_generate_template(
    template_id: str,
    payload: QuickGenerateRequest | None = Body(default=None),
    authorization: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[SystemQuickGenerateResult]:
    """POST /api/v1/me/character-templates/{templateId}/quick-generate。

    一键生成一整份建卡态数据并写进这张卡。不生成 AI 背景故事（见 service 层）。
    """
    user_id = await _require_user_id(authorization, db)
    try:
        _, ruleset = await _template_ruleset(db, user_id, template_id)
        result = await character_service.quick_generate_template(
            db, user_id, template_id, ruleset, payload
        )
    except character_service.CharacterNotFoundError as exc:
        raise _not_found(exc) from exc
    except character_service.CharacterTemplateDuplicateError as exc:
        raise _duplicate(exc) from exc
    except CharacterGenerationError as exc:
        raise AppException(ErrorCode.CONFLICT, str(exc), status.HTTP_409_CONFLICT) from exc
    return ApiResponse.ok(result)
