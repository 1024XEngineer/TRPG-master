"""Controller 层：`/api/v1/modules` 路由 —— 模组目录 + 导入（issue #77 补充
模组详情 / 导入 2 个新端点）。

`GET /modules`、`GET /modules/{moduleId}` 是真实的数据库查询（内容库
`Scenario` 表）；`POST /modules/import`、`GET /modules/import/{jobId}`
依赖真实 LLM 解析管线（归 #57），本期固定 NOT_IMPLEMENTED（issue 决策 7）。
"""

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.common import ApiResponse
from app.dto.module import ModuleDetailRead, ModuleImportJobRead, ModuleImportRequestBody
from app.dto.room import ModuleRead
from app.service import module_import as module_import_service
from app.service import room as room_service

router = APIRouter(prefix="/modules", tags=["modules"])


@router.get("", response_model=ApiResponse[list[ModuleRead]])
async def list_modules(db: AsyncSession = Depends(get_db)) -> ApiResponse[list[ModuleRead]]:
    """GET /api/v1/modules —— 获取可用模组列表。"""
    modules = await room_service.list_modules(db)
    return ApiResponse.ok(modules)


@router.get("/{module_id}", response_model=ApiResponse[ModuleDetailRead])
async def get_module_detail(
    module_id: str, db: AsyncSession = Depends(get_db)
) -> ApiResponse[ModuleDetailRead]:
    """GET /api/v1/modules/{moduleId} —— 模组详情。"""
    module = await room_service.get_module_detail(db, module_id)
    if module is None:
        raise AppException(ErrorCode.NOT_FOUND, "模组不存在", status.HTTP_404_NOT_FOUND)
    return ApiResponse.ok(module)


@router.post(
    "/import", response_model=ApiResponse[ModuleImportJobRead], status_code=status.HTTP_201_CREATED
)
async def import_module(
    payload: ModuleImportRequestBody, db: AsyncSession = Depends(get_db)
) -> ApiResponse[ModuleImportJobRead]:
    """POST /api/v1/modules/import —— 导入模组（提交异步任务，本期未实现）。"""
    job = await module_import_service.start_import(db, payload)
    return ApiResponse.ok(job)


@router.get("/import/{job_id}", response_model=ApiResponse[ModuleImportJobRead])
async def get_import_job(
    job_id: str, db: AsyncSession = Depends(get_db)
) -> ApiResponse[ModuleImportJobRead]:
    """GET /api/v1/modules/import/{jobId} —— 轮询导入任务状态（本期未实现）。"""
    job = await module_import_service.get_import_job(db, job_id)
    return ApiResponse.ok(job)
