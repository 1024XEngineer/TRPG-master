"""Character portrait generation endpoint."""

from fastapi import APIRouter, Depends, Header, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.common import ApiResponse
from app.dto.portrait import PortraitGenerationRequest, PortraitGenerationResult
from app.service import room as room_service
from app.service.portrait_generation import (
    PortraitCharacterIncompleteError,
    PortraitCharacterNotFoundError,
    PortraitGenerationDisabledError,
    PortraitGenerationInProgressError,
    PortraitGenerationService,
    PortraitImageContentRejectedError,
    PortraitImageGenerationError,
    PortraitImageTimeoutError,
)

router = APIRouter(prefix="/rooms", tags=["character-portraits"])


def _etag_matches(if_none_match: str | None, current_etag: str) -> bool:
    """按 GET 的弱比较语义判断客户端缓存版本是否仍然有效。"""
    if not if_none_match:
        return False
    for candidate in if_none_match.split(","):
        normalized = candidate.strip()
        if normalized == "*" or normalized.removeprefix("W/") == current_etag:
            return True
    return False


def get_portrait_generation_service(request: Request) -> PortraitGenerationService:
    return request.app.state.portrait_generation_service


@router.get("/{room_id}/players/{player_id}/portrait", response_class=Response)
async def get_player_portrait(
    room_id: str,
    player_id: str,
    _version: str | None = Query(default=None, alias="v"),
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    if_none_match: str | None = Header(default=None, alias="If-None-Match"),
    db: AsyncSession = Depends(get_db),
    service: PortraitGenerationService = Depends(get_portrait_generation_service),
) -> Response:
    """鉴权读取玩家头像；查询参数只负责浏览器缓存分版，不参与身份判断。"""
    try:
        portrait = await service.get_player_portrait(db, room_id, player_id, reconnect_token)
    except PortraitCharacterNotFoundError as exc:
        raise AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND) from exc
    except room_service.RoomAuthenticationError as exc:
        raise AppException(ErrorCode.UNAUTHORIZED, str(exc), status.HTTP_401_UNAUTHORIZED) from exc
    except room_service.RoomAuthorizationError as exc:
        raise AppException(ErrorCode.FORBIDDEN, str(exc), status.HTTP_403_FORBIDDEN) from exc
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
        headers={
            "Content-Length": str(len(portrait.content)),
            **cache_headers,
        },
    )


@router.post(
    "/{room_id}/characters/{character_id}/portrait-generations",
    response_model=ApiResponse[PortraitGenerationResult],
)
async def generate_character_portrait(
    room_id: str,
    character_id: str,
    payload: PortraitGenerationRequest,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
    service: PortraitGenerationService = Depends(get_portrait_generation_service),
) -> ApiResponse[PortraitGenerationResult]:
    try:
        result = await service.generate(db, room_id, character_id, reconnect_token, payload)
    except PortraitGenerationDisabledError as exc:
        raise AppException(
            ErrorCode.PORTRAIT_GENERATION_DISABLED,
            str(exc),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    except PortraitCharacterNotFoundError as exc:
        raise AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND) from exc
    except room_service.RoomAuthenticationError as exc:
        raise AppException(ErrorCode.UNAUTHORIZED, str(exc), status.HTTP_401_UNAUTHORIZED) from exc
    except room_service.RoomAuthorizationError as exc:
        raise AppException(ErrorCode.FORBIDDEN, str(exc), status.HTTP_403_FORBIDDEN) from exc
    except PortraitCharacterIncompleteError as exc:
        raise AppException(
            ErrorCode.CHARACTER_INCOMPLETE,
            str(exc),
            status.HTTP_409_CONFLICT,
        ) from exc
    except PortraitGenerationInProgressError as exc:
        raise AppException(
            ErrorCode.PORTRAIT_GENERATION_IN_PROGRESS,
            str(exc),
            status.HTTP_409_CONFLICT,
        ) from exc
    except PortraitImageContentRejectedError as exc:
        raise AppException(
            ErrorCode.PORTRAIT_CONTENT_REJECTED,
            str(exc),
            status.HTTP_422_UNPROCESSABLE_CONTENT,
        ) from exc
    except PortraitImageTimeoutError as exc:
        raise AppException(
            ErrorCode.PORTRAIT_GENERATION_TIMEOUT,
            str(exc),
            status.HTTP_504_GATEWAY_TIMEOUT,
        ) from exc
    except PortraitImageGenerationError as exc:
        raise AppException(
            ErrorCode.PORTRAIT_GENERATION_FAILED,
            str(exc),
            status.HTTP_502_BAD_GATEWAY,
        ) from exc
    return ApiResponse.ok(result)
