"""Grounded, review-before-commit ending API (#212 §10)."""

from typing import NoReturn

from collaboration_framework.contracts import (
    ConfirmEndingDraftRequest,
    ConfirmEndingDraftResult,
    CreateEndingDraftRequest,
    EndingDraft,
)
from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.common import ApiResponse
from app.service import ending as ending_service
from app.service import room as room_service
from app.service.ws_events import broadcast_room_state

router = APIRouter(prefix="/rooms", tags=["endings"])


def _raise_public_error(exc: Exception) -> NoReturn:
    if isinstance(exc, ending_service.EndingNotFoundError):
        raise AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND) from exc
    if isinstance(exc, ending_service.EndingDraftStaleError):
        raise AppException(
            ErrorCode.ENDING_DRAFT_STALE, str(exc), status.HTTP_409_CONFLICT
        ) from exc
    if isinstance(exc, ending_service.EndingUnavailableError):
        raise AppException(
            ErrorCode.ENDING_UNAVAILABLE, str(exc), status.HTTP_409_CONFLICT
        ) from exc
    if isinstance(exc, ending_service.EndingConflictError):
        raise AppException(ErrorCode.CONFLICT, str(exc), status.HTTP_409_CONFLICT) from exc
    if isinstance(exc, room_service.RoomAuthenticationError):
        raise AppException(ErrorCode.UNAUTHORIZED, str(exc), status.HTTP_401_UNAUTHORIZED) from exc
    if isinstance(exc, room_service.RoomAuthorizationError):
        raise AppException(ErrorCode.FORBIDDEN, str(exc), status.HTTP_403_FORBIDDEN) from exc
    raise exc


async def _member(db: AsyncSession, room_id: str, reconnect_token: str | None):
    try:
        return await room_service.require_room_member(db, room_id, reconnect_token)
    except Exception as exc:
        _raise_public_error(exc)


@router.post(
    "/{room_id}/ending-drafts",
    response_model=ApiResponse[EndingDraft],
)
async def create_ending_draft(
    room_id: str,
    payload: CreateEndingDraftRequest,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[EndingDraft]:
    player = await _member(db, room_id, reconnect_token)
    try:
        result = await ending_service.create_draft(
            db, room_id=room_id, player=player, request=payload
        )
    except Exception as exc:
        _raise_public_error(exc)
    return ApiResponse.ok(result)


@router.post(
    "/{room_id}/ending-drafts/{draft_id}/confirm",
    response_model=ApiResponse[ConfirmEndingDraftResult],
)
async def confirm_ending_draft(
    room_id: str,
    draft_id: str,
    payload: ConfirmEndingDraftRequest,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ConfirmEndingDraftResult]:
    player = await _member(db, room_id, reconnect_token)
    try:
        result = await ending_service.confirm_draft(
            db,
            room_id=room_id,
            draft_id=draft_id,
            player=player,
            request=payload,
        )
    except Exception as exc:
        _raise_public_error(exc)
    await broadcast_room_state(db, room_id)
    return ApiResponse.ok(result)
