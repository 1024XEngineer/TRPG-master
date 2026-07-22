"""Service 层：模组导入（issue #77 §2 新增端点）。

真实的 LLM 解析管线归 #57，本期两个接口固定返回 NOT_IMPLEMENTED（issue
决策 7）——不落库、不创建任何 `module_import_jobs` 行，保持"没有实现就不要
假装有数据"的诚实。
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import not_implemented
from app.dto.module import ModuleImportJobRead, ModuleImportRequestBody


async def start_import(db: AsyncSession, payload: ModuleImportRequestBody) -> ModuleImportJobRead:
    raise not_implemented("模组导入依赖真实 LLM 解析管线，本期尚未实现")


async def get_import_job(db: AsyncSession, job_id: str) -> ModuleImportJobRead:
    raise not_implemented("模组导入依赖真实 LLM 解析管线，本期尚未实现")
