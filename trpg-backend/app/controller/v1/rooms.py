"""Controller 层：`/api/v1/rooms` 路由 —— 房间 CRUD 和生命周期管理。

MS1 使用内存 stub（app/service/room.py），后续接入数据库后照搬 examples.py
的模式改为 SQLAlchemy 异步操作。
"""

from typing import NoReturn

from fastapi import APIRouter, Header, status

from app.core.errors import AppException, ErrorCode
from app.dto.character import CharacterDraftResult, CharacterUpdateBody
from app.dto.common import ApiResponse
from app.dto.room import (
    JoinRoomBody,
    RoomCreate,
    RoomCreateResult,
    RoomPreview,
    SelectModuleBody,
)
from app.service import room as room_service

router = APIRouter(prefix="/rooms", tags=["rooms"])


def _raise_service_error(exc: Exception) -> NoReturn:
    if isinstance(exc, room_service.RoomAuthenticationError):
        raise AppException(ErrorCode.UNAUTHORIZED, str(exc), status.HTTP_401_UNAUTHORIZED) from exc
    if isinstance(exc, room_service.RoomAuthorizationError):
        raise AppException(ErrorCode.FORBIDDEN, str(exc), status.HTTP_403_FORBIDDEN) from exc
    if isinstance(exc, room_service.RoomConflictError):
        raise AppException(ErrorCode.CONFLICT, str(exc), status.HTTP_409_CONFLICT) from exc
    raise AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND) from exc


@router.post("", response_model=ApiResponse[RoomCreateResult])
async def create_room(payload: RoomCreate) -> ApiResponse[RoomCreateResult]:
    """POST /api/v1/rooms —— 创建房间，返回房间身份信息。"""
    result = await room_service.create_room(payload)
    return ApiResponse.ok(result)


@router.post("/{room_id}/module", response_model=ApiResponse[None])
async def select_room_module(
    room_id: str,
    payload: SelectModuleBody,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
) -> ApiResponse[None]:
    """POST /api/v1/rooms/{roomId}/module —— 房主选定模组。"""
    try:
        await room_service.select_module(room_id, payload, reconnect_token)
    except (
        room_service.RoomNotFoundError,
        room_service.RoomAuthenticationError,
        room_service.RoomAuthorizationError,
        room_service.RoomConflictError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(None)


@router.post("/{room_code}/join", response_model=ApiResponse[RoomCreateResult])
async def join_room(room_code: str, payload: JoinRoomBody) -> ApiResponse[RoomCreateResult]:
    """POST /api/v1/rooms/{roomCode}/join —— 用房间码加入房间。"""
    try:
        result = await room_service.join_room(room_code, payload)
    except (room_service.RoomNotFoundError, room_service.RoomConflictError) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(result)


@router.get("/{room_code}", response_model=ApiResponse[RoomPreview])
async def get_room_info(room_code: str) -> ApiResponse[RoomPreview]:
    """GET /api/v1/rooms/{roomCode} —— 获取房间信息 + 玩家列表。"""
    preview = await room_service.get_room_preview(room_code)
    if preview is None:
        raise AppException(ErrorCode.NOT_FOUND, "房间不存在", status.HTTP_404_NOT_FOUND)
    return ApiResponse.ok(preview)


@router.post("/{room_id}/start-story", response_model=ApiResponse[None])
async def start_story(
    room_id: str,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
) -> ApiResponse[None]:
    """POST /api/v1/rooms/{roomId}/start-story —— 房主开始游戏。"""
    try:
        await room_service.start_story(room_id, reconnect_token)
    except (
        room_service.RoomNotFoundError,
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
) -> ApiResponse[None]:
    """POST /api/v1/rooms/{roomId}/end —— 房主结束游戏。"""
    try:
        await room_service.end_game(room_id, reconnect_token)
    except (
        room_service.RoomNotFoundError,
        room_service.RoomAuthenticationError,
        room_service.RoomAuthorizationError,
        room_service.RoomConflictError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(None)


@router.post(
    "/{room_id}/characters",
    response_model=ApiResponse[CharacterDraftResult],
    status_code=status.HTTP_201_CREATED,
    tags=["characters"],
)
async def create_character(
    room_id: str,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
) -> ApiResponse[CharacterDraftResult]:
    """POST /api/v1/rooms/{roomId}/characters —— 玩家创建一份角色草稿。"""
    try:
        result = await room_service.create_character_draft(room_id, reconnect_token)
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
) -> ApiResponse[None]:
    """PATCH /api/v1/rooms/{roomId}/characters/{characterId} —— 保存建卡向导算好的完整角色数据。"""
    try:
        await room_service.update_character(room_id, character_id, payload, reconnect_token)
    except (
        room_service.RoomNotFoundError,
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
) -> ApiResponse[None]:
    """POST /api/v1/rooms/{roomId}/characters/{characterId}/complete —— 标记建卡完成。"""
    try:
        await room_service.complete_character(room_id, character_id, reconnect_token)
    except (
        room_service.RoomNotFoundError,
        room_service.RoomAuthenticationError,
        room_service.RoomAuthorizationError,
    ) as exc:
        _raise_service_error(exc)
    return ApiResponse.ok(None)
