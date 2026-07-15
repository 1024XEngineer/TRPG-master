"""Controller 层：`/api/v1/examples` 路由，GET(列表/单个)/POST/PUT/DELETE 全套 CRUD 范例。

跟真实业务完全无关，只用来演示这套骨架的完整用法：怎么用 Depends(get_db) 拿
数据库会话、怎么用 AppException 表达业务错误（404/409）、controller 怎么调用
service 层、怎么把校验/DTO/响应封装拼起来。以后写真实业务接口时，照这个文件的
结构抄一份就行。
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.common import ApiResponse
from app.dto.example import ExampleCreate, ExampleRead, ExampleUpdate
from app.models.example import Example
from app.service import example as example_service

router = APIRouter(prefix="/examples", tags=["examples"])


async def _get_example_or_404(db: AsyncSession, example_id: str) -> Example:
    """查不到就直接抛 404，多个路由函数（get/put/delete）都要做这个判断，抽出来复用。"""
    example = await example_service.get_example(db, example_id)
    if example is None:
        raise AppException(ErrorCode.NOT_FOUND, "示例不存在", status.HTTP_404_NOT_FOUND)
    return example


async def _ensure_name_available(
    db: AsyncSession, name: str, *, exclude_id: str | None = None
) -> None:
    """检查名称是否可用（新建时 exclude_id=None；更新时排除自己这一条，允许"改成同一个名字"）。

    这只是给常见的顺序请求场景一个快速、友好的报错；两个并发请求都可能通过
    这里的检查，真正兜底靠的是下面 create/update 里对 IntegrityError 的捕获。
    """
    existing = await example_service.get_example_by_name(db, name)
    if existing is not None and existing.id != exclude_id:
        raise AppException(ErrorCode.CONFLICT, "同名示例已存在", status.HTTP_409_CONFLICT)


@router.get("", response_model=ApiResponse[list[ExampleRead]])
async def list_examples(db: AsyncSession = Depends(get_db)) -> ApiResponse[list[ExampleRead]]:
    """GET /api/v1/examples —— 列出全部记录，200。"""
    examples = await example_service.list_examples(db)
    return ApiResponse.ok([ExampleRead.model_validate(e) for e in examples])


@router.get("/{example_id}", response_model=ApiResponse[ExampleRead])
async def get_example(
    example_id: str, db: AsyncSession = Depends(get_db)
) -> ApiResponse[ExampleRead]:
    """GET /api/v1/examples/{id} —— 查单条，查不到 404。"""
    example = await _get_example_or_404(db, example_id)
    return ApiResponse.ok(ExampleRead.model_validate(example))


@router.post("", response_model=ApiResponse[ExampleRead], status_code=status.HTTP_201_CREATED)
async def create_example(
    payload: ExampleCreate, db: AsyncSession = Depends(get_db)
) -> ApiResponse[ExampleRead]:
    """POST /api/v1/examples —— 新建，成功 201；名称重复 409；
    请求体不合法 422（由 pydantic 自动处理）。"""
    await _ensure_name_available(db, payload.name)
    try:
        example = await example_service.create_example(db, payload)
    except IntegrityError as exc:
        # 两个并发请求都通过了上面的查重，最终只有一个能提交成功——这里兜住
        # 真正撞库的那一个，转成跟"提前查重"命中时一样的 409，而不是让它变成
        # 一个 500（对客户端来说，"名字被别人抢先用了"永远应该是 409）。
        raise AppException(ErrorCode.CONFLICT, "同名示例已存在", status.HTTP_409_CONFLICT) from exc
    return ApiResponse.ok(ExampleRead.model_validate(example))


@router.put("/{example_id}", response_model=ApiResponse[ExampleRead])
async def update_example(
    example_id: str, payload: ExampleUpdate, db: AsyncSession = Depends(get_db)
) -> ApiResponse[ExampleRead]:
    """PUT /api/v1/examples/{id} —— 全量更新；记录不存在 404；改成别人的名称 409。"""
    example = await _get_example_or_404(db, example_id)
    await _ensure_name_available(db, payload.name, exclude_id=example_id)
    try:
        example = await example_service.update_example(db, example, payload)
    except IntegrityError as exc:
        raise AppException(ErrorCode.CONFLICT, "同名示例已存在", status.HTTP_409_CONFLICT) from exc
    return ApiResponse.ok(ExampleRead.model_validate(example))


@router.delete("/{example_id}", response_model=ApiResponse[None])
async def delete_example(example_id: str, db: AsyncSession = Depends(get_db)) -> ApiResponse[None]:
    """DELETE /api/v1/examples/{id} —— 删除；记录不存在 404；成功返回 data=null，状态码仍是 200
    （没有用 204 No Content，是为了让所有接口都能返回同一种统一响应信封，不用为
    "没有响应体"的情况另外特殊处理）。
    """
    example = await _get_example_or_404(db, example_id)
    await example_service.delete_example(db, example)
    return ApiResponse.ok(None)
