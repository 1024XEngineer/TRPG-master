"""Room inventory draft review, projection and custody commands (#212 §9)."""

from typing import NoReturn

from collaboration_framework.contracts import (
    ChangeItemCustodyRequest,
    ChangeItemCustodyResult,
    ConfirmInventoryImportDraftRequest,
    ConfirmInventoryImportResult,
    CreateInventoryImportDraftRequest,
    InventoryImportDraft,
    InventoryView,
)
from fastapi import APIRouter, Depends, Header, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.common import ApiResponse
from app.service import inventory as inventory_service
from app.service import room as room_service

router = APIRouter(prefix="/rooms", tags=["inventory"])


def _raise_public_error(exc: Exception) -> NoReturn:
    if isinstance(exc, inventory_service.InventoryNotFoundError):
        raise AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND) from exc
    if isinstance(exc, inventory_service.ItemAlreadyTakenError):
        raise AppException(
            ErrorCode.ITEM_ALREADY_TAKEN, str(exc), status.HTTP_409_CONFLICT
        ) from exc
    if isinstance(exc, inventory_service.ItemVersionConflictError):
        raise AppException(
            ErrorCode.ITEM_VERSION_CONFLICT, str(exc), status.HTTP_409_CONFLICT
        ) from exc
    if isinstance(exc, inventory_service.InventoryRevisionConflictError):
        raise AppException(ErrorCode.REVISION_CONFLICT, str(exc), status.HTTP_409_CONFLICT) from exc
    if isinstance(exc, inventory_service.InventoryConflictError):
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
    "/{room_id}/inventory-import-drafts",
    response_model=ApiResponse[InventoryImportDraft],
)
async def create_inventory_import_draft(
    room_id: str,
    payload: CreateInventoryImportDraftRequest,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[InventoryImportDraft]:
    player = await _member(db, room_id, reconnect_token)
    try:
        result = await inventory_service.create_import_draft(
            db, room_id=room_id, player=player, request=payload
        )
    except Exception as exc:
        _raise_public_error(exc)
    return ApiResponse.ok(result)


@router.post(
    "/{room_id}/inventory-import-drafts/{draft_id}/confirm",
    response_model=ApiResponse[ConfirmInventoryImportResult],
)
async def confirm_inventory_import_draft(
    room_id: str,
    draft_id: str,
    payload: ConfirmInventoryImportDraftRequest,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ConfirmInventoryImportResult]:
    player = await _member(db, room_id, reconnect_token)
    try:
        result = await inventory_service.confirm_import_draft(
            db,
            room_id=room_id,
            draft_id=draft_id,
            player=player,
            request=payload,
        )
    except Exception as exc:
        _raise_public_error(exc)
    return ApiResponse.ok(result)


@router.get("/{room_id}/inventory", response_model=ApiResponse[InventoryView])
async def get_inventory(
    room_id: str,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[InventoryView]:
    player = await _member(db, room_id, reconnect_token)
    try:
        result = await inventory_service.inventory_view(db, room_id=room_id, player=player)
    except Exception as exc:
        _raise_public_error(exc)
    return ApiResponse.ok(result)


@router.post(
    "/{room_id}/items/{item_id}/custody",
    response_model=ApiResponse[ChangeItemCustodyResult],
)
async def change_item_custody(
    room_id: str,
    item_id: str,
    payload: ChangeItemCustodyRequest,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
) -> ApiResponse[ChangeItemCustodyResult]:
    player = await _member(db, room_id, reconnect_token)
    try:
        result = await inventory_service.change_custody(
            db,
            room_id=room_id,
            item_id=item_id,
            player=player,
            request=payload,
        )
    except Exception as exc:
        _raise_public_error(exc)
    return ApiResponse.ok(result)
