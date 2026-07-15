from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.crud import example as example_crud
from app.models.example import Example
from app.schemas.common import ApiResponse
from app.schemas.example import ExampleCreate, ExampleRead, ExampleUpdate

router = APIRouter(prefix="/examples", tags=["examples"])


async def _get_example_or_404(db: AsyncSession, example_id: str) -> Example:
    example = await example_crud.get_example(db, example_id)
    if example is None:
        raise AppException(ErrorCode.NOT_FOUND, "示例不存在", status.HTTP_404_NOT_FOUND)
    return example


async def _ensure_name_available(
    db: AsyncSession, name: str, *, exclude_id: str | None = None
) -> None:
    existing = await example_crud.get_example_by_name(db, name)
    if existing is not None and existing.id != exclude_id:
        raise AppException(ErrorCode.CONFLICT, "同名示例已存在", status.HTTP_409_CONFLICT)


@router.get("", response_model=ApiResponse[list[ExampleRead]])
async def list_examples(db: AsyncSession = Depends(get_db)) -> ApiResponse[list[ExampleRead]]:
    examples = await example_crud.list_examples(db)
    return ApiResponse.ok([ExampleRead.model_validate(e) for e in examples])


@router.get("/{example_id}", response_model=ApiResponse[ExampleRead])
async def get_example(
    example_id: str, db: AsyncSession = Depends(get_db)
) -> ApiResponse[ExampleRead]:
    example = await _get_example_or_404(db, example_id)
    return ApiResponse.ok(ExampleRead.model_validate(example))


@router.post("", response_model=ApiResponse[ExampleRead], status_code=status.HTTP_201_CREATED)
async def create_example(
    payload: ExampleCreate, db: AsyncSession = Depends(get_db)
) -> ApiResponse[ExampleRead]:
    await _ensure_name_available(db, payload.name)
    example = await example_crud.create_example(db, payload)
    return ApiResponse.ok(ExampleRead.model_validate(example))


@router.put("/{example_id}", response_model=ApiResponse[ExampleRead])
async def update_example(
    example_id: str, payload: ExampleUpdate, db: AsyncSession = Depends(get_db)
) -> ApiResponse[ExampleRead]:
    example = await _get_example_or_404(db, example_id)
    await _ensure_name_available(db, payload.name, exclude_id=example_id)
    example = await example_crud.update_example(db, example, payload)
    return ApiResponse.ok(ExampleRead.model_validate(example))


@router.delete("/{example_id}", response_model=ApiResponse[None])
async def delete_example(example_id: str, db: AsyncSession = Depends(get_db)) -> ApiResponse[None]:
    example = await _get_example_or_404(db, example_id)
    await example_crud.delete_example(db, example)
    return ApiResponse.ok(None)
