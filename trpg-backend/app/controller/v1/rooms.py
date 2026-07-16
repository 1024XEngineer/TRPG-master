"""Controller 层：`/api/v1/rooms` 路由 —— 房间 CRUD 和生命周期管理（issue #77
切换为真实数据库读写 + 补充 roll-attributes / summary / replay 3 个新端点）。

角色卡相关路由（挂在 `/rooms/{roomId}/characters` 下）本期改为调用独立的
`service/character.py`，不再是 `room_service` 的一部分（issue #77 决策：
`auth`/`room`/`character`/`ws` 四个 service 各自独立）。
"""

from typing import NoReturn

from fastapi import APIRouter, Body, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.controller.dependencies import get_optional_user
from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.character import (
    CharacterCreateBody,
    CharacterDraftResult,
    CharacterUpdateBody,
    RollAttributesResult,
)
from app.dto.common import ApiResponse
from app.dto.replay import ReplayEventRead, RoomSummaryRead
from app.dto.room import (
    JoinRoomBody,
    RoomCreate,
    RoomCreateResult,
    RoomPreview,
    SelectModuleBody,
)
from app.models.user import User
from app.service import character as character_service
from app.service import room as room_service

router = APIRouter(prefix="/rooms", tags=["rooms"])

# 房间域的异常 → (错误码, HTTP 状态码) 映射表。issue #77 决策 2：业务语义层的
# 错误码以架构文档为准，这里把"房间不存在"/"房间已满"/"未选模组"这些原来共用
# 通用 NOT_FOUND/CONFLICT 的场景拆成更具体的业务码；找不到映射的异常兜底成
# NOT_FOUND，保持原来的行为（角色/模组这类没有专属业务码的"找不到"场景）。
_ERROR_MAP: dict[type[Exception], tuple[ErrorCode, int]] = {
    room_service.RoomNotFoundError: (ErrorCode.ROOM_NOT_FOUND, status.HTTP_404_NOT_FOUND),
    room_service.ModuleNotFoundError: (ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND),
    room_service.RoomFullError: (ErrorCode.ROOM_FULL, status.HTTP_409_CONFLICT),
    room_service.ModuleNotSelectedError: (ErrorCode.MODULE_NOT_SELECTED, status.HTTP_409_CONFLICT),
    room_service.CharacterIncompleteError: (
        ErrorCode.CHARACTER_INCOMPLETE,
        status.HTTP_409_CONFLICT,
    ),
    room_service.RoomConflictError: (ErrorCode.CONFLICT, status.HTTP_409_CONFLICT),
    room_service.RoomAuthenticationError: (ErrorCode.UNAUTHORIZED, status.HTTP_401_UNAUTHORIZED),
    room_service.RoomAuthorizationError: (ErrorCode.FORBIDDEN, status.HTTP_403_FORBIDDEN),
    character_service.CharacterNotFoundError: (ErrorCode.NOT_FOUND, status.HTTP_404_NOT_FOUND),
}


def _raise_service_error(exc: Exception) -> NoReturn:
    for exc_type, (code, http_status) in _ERROR_MAP.items():
        if isinstance(exc, exc_type):
            raise AppException(code, str(exc), http_status) from exc
    raise AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND) from exc


@router.post("", response_model=ApiResponse[RoomCreateResult])
async def create_room(
    payload: RoomCreate,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> ApiResponse[RoomCreateResult]:
    """POST /api/v1/rooms —— 创建房间，返回房间身份信息。"""
    result = await room_service.create_room(db, payload, user)
    return ApiResponse.ok(result)


@router.post("/{room_id}/module", response_model=ApiResponse[None])
async def select_room_module(
    room_id: str,
    payload: SelectModuleBody,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """POST /api/v1/rooms/{roomId}/module —— 房主选定模组。"""
    try:
        await room_service.select_module(db, room_id, payload, reconnect_token)
    except (
        room_service.RoomNotFoundError,
        room_service.ModuleNotFoundError,
        room_service.RoomAuthenticationError,
        room_service.RoomAuthorizationError,
        room_service.RoomConflictError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(None)


@router.post("/{room_code}/join", response_model=ApiResponse[RoomCreateResult])
async def join_room(
    room_code: str,
    payload: JoinRoomBody,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_optional_user),
) -> ApiResponse[RoomCreateResult]:
    """POST /api/v1/rooms/{roomCode}/join —— 用房间码加入房间。"""
    try:
        result = await room_service.join_room(db, room_code, payload, user)
    except (
        room_service.RoomNotFoundError,
        room_service.RoomFullError,
        room_service.RoomConflictError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(result)


@router.get("/{room_code}", response_model=ApiResponse[RoomPreview])
async def get_room_info(
    room_code: str, db: AsyncSession = Depends(get_db)
) -> ApiResponse[RoomPreview]:
    """GET /api/v1/rooms/{roomCode} —— 获取房间信息 + 玩家列表。"""
    preview = await room_service.get_room_preview(db, room_code)
    if preview is None:
        raise AppException(ErrorCode.ROOM_NOT_FOUND, "房间不存在", status.HTTP_404_NOT_FOUND)
    return ApiResponse.ok(preview)


@router.post("/{room_id}/start-story", response_model=ApiResponse[None])
async def start_story(
    room_id: str,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """POST /api/v1/rooms/{roomId}/start-story —— 房主开始游戏。"""
    try:
        await room_service.start_story(db, room_id, reconnect_token)
    except (
        room_service.RoomNotFoundError,
        room_service.ModuleNotSelectedError,
        room_service.RoomAuthenticationError,
        room_service.RoomAuthorizationError,
        room_service.RoomConflictError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(None)


@router.post("/{room_id}/end", response_model=ApiResponse[None])
async def end_game(
    room_id: str,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """POST /api/v1/rooms/{roomId}/end —— 房主结束游戏。"""
    try:
        await room_service.end_game(db, room_id, reconnect_token)
    except (
        room_service.RoomNotFoundError,
        room_service.RoomAuthenticationError,
        room_service.RoomAuthorizationError,
        room_service.RoomConflictError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(None)


@router.get("/{room_id}/summary", response_model=ApiResponse[RoomSummaryRead])
async def get_room_summary(
    room_id: str, db: AsyncSession = Depends(get_db)
) -> ApiResponse[RoomSummaryRead]:
    """GET /api/v1/rooms/{roomId}/summary —— 复盘摘要（本期未实现）。"""
    summary = await room_service.get_summary(db, room_id)
    return ApiResponse.ok(summary)


@router.get("/{room_id}/replay", response_model=ApiResponse[list[ReplayEventRead]])
async def get_room_replay(
    room_id: str,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[list[ReplayEventRead]]:
    """GET /api/v1/rooms/{roomId}/replay —— 逐条事件回放（仅本房间成员可查）。"""
    try:
        events = await room_service.get_replay(db, room_id, reconnect_token)
    except (
        room_service.RoomAuthenticationError,
        room_service.RoomAuthorizationError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(events)


# ── 角色（issue #59，本期切到 service/character.py） ──────────────────────────


@router.post(
    "/{room_id}/characters",
    response_model=ApiResponse[CharacterDraftResult],
    status_code=status.HTTP_201_CREATED,
    tags=["characters"],
)
async def create_character(
    room_id: str,
    payload: CharacterCreateBody | None = Body(default=None),
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[CharacterDraftResult]:
    """POST /api/v1/rooms/{roomId}/characters —— 玩家创建一份角色草稿。

    `basedOnTemplateId`（issue #77 新增第三条建卡路径，见 CharacterCreateBody
    的说明）本期未实现，带了这个字段会直接收到 NOT_IMPLEMENTED。
    """
    based_on_template_id = payload.based_on_template_id if payload else None
    try:
        result = await character_service.create_character_draft(
            db, room_id, reconnect_token, based_on_template_id
        )
    except (
        room_service.RoomNotFoundError,
        room_service.RoomAuthenticationError,
        room_service.RoomAuthorizationError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(result)


@router.patch(
    "/{room_id}/characters/{character_id}",
    response_model=ApiResponse[None],
    tags=["characters"],
)
async def update_character(
    room_id: str,
    character_id: str,
    payload: CharacterUpdateBody,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """PATCH /api/v1/rooms/{roomId}/characters/{characterId} —— 保存建卡向导算好的完整角色数据。"""
    try:
        await character_service.update_character(
            db, room_id, character_id, payload, reconnect_token
        )
    except (
        character_service.CharacterNotFoundError,
        room_service.RoomAuthenticationError,
        room_service.RoomAuthorizationError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(None)


@router.post(
    "/{room_id}/characters/{character_id}/complete",
    response_model=ApiResponse[None],
    tags=["characters"],
)
async def complete_character(
    room_id: str,
    character_id: str,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[None]:
    """POST /api/v1/rooms/{roomId}/characters/{characterId}/complete —— 标记建卡完成。"""
    try:
        await character_service.complete_character(db, room_id, character_id, reconnect_token)
    except (
        character_service.CharacterNotFoundError,
        room_service.RoomAuthenticationError,
        room_service.RoomAuthorizationError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(None)


@router.post(
    "/{room_id}/characters/{character_id}/roll-attributes",
    response_model=ApiResponse[RollAttributesResult],
    tags=["characters"],
)
async def roll_attributes(
    room_id: str,
    character_id: str,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[RollAttributesResult]:
    """POST /api/v1/rooms/{roomId}/characters/{characterId}/roll-attributes ——
    服务端权威掷骰生成属性（issue #77 新增，真实实现，不是 NOT_IMPLEMENTED 桩）。
    """
    try:
        result = await character_service.roll_attributes(db, room_id, character_id, reconnect_token)
    except (
        character_service.CharacterNotFoundError,
        room_service.RoomAuthenticationError,
        room_service.RoomAuthorizationError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(result)
