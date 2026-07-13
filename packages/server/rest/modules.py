"""模组目录与导入 —— 对应 API 对齐规范 §2.3/§2.4/§2.5。

导入是"提交任务(202)+轮询状态"两段式（2026-07-11 由同步改异步），因为真实
场景是上传原始材料要走 LLM/Agent 解析，耗时不定、可能失败。
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile
from server.rest.schema import CamelModel
from sqlalchemy import select

from core.content.db_models import ModulePackRow
from core.db import get_sessionmaker

router = APIRouter(tags=["modules"])


class ModuleMetaResponse(CamelModel):
    id: str
    title: str
    version: str
    authors: list[str]
    players_min: int
    players_max: int
    difficulty: int
    estimated_duration: Optional[str] = None


@router.get("/modules")
async def list_modules(system_id: Optional[str] = None) -> dict:
    """★ 本次不做模组导入，只返回真正落库的内置模组（见 scripts/seed_demo_module.py）。"""
    async with get_sessionmaker()() as session:
        rows = (await session.execute(select(ModulePackRow))).scalars().all()
        return {
            "modules": [
                ModuleMetaResponse(
                    id=row.id,
                    title=row.title,
                    version=row.version,
                    authors=row.authors or [],
                    players_min=row.players_min,
                    players_max=row.players_max,
                    difficulty=row.difficulty,
                    estimated_duration=row.estimated_duration,
                ).model_dump(by_alias=True)
                for row in rows
            ]
        }


class ImportAcceptedResponse(CamelModel):
    import_job_id: str
    status: str = "queued"


@router.post("/modules/import", status_code=202)
async def import_module(material: UploadFile) -> ImportAcceptedResponse:
    """🔒 需登录。上传前粗检（文件层面，不涉及内容语义）→ 202 + importJobId。"""
    raise NotImplementedError("POST /modules/import 待实现（core.moduleimport.ModuleImportAgent）")


class ImportJobStatus(CamelModel):
    import_job_id: str
    status: str  # queued/parsing/validating/failed/succeeded
    fail_step: Optional[str] = None
    fail_reason: Optional[str] = None
    result_module_id: Optional[str] = None
    parsed_by_model: Optional[str] = None


@router.get("/modules/import/{import_job_id}")
async def get_import_job(import_job_id: str) -> ImportJobStatus:
    """仅上传者本人可查。前端建议 2~3 秒轮一次，轮到 failed/succeeded 停止。"""
    raise NotImplementedError("GET /modules/import/{importJobId} 待实现")


@router.get("/modules/{module_id}")
async def get_module_detail(module_id: str) -> ModuleMetaResponse:
    """不含 npcs.secrets 等只在 GodView 可见的字段，即便是给房主预览也不下发底牌。"""
    async with get_sessionmaker()() as session:
        row = await session.get(ModulePackRow, module_id)
        if row is None:
            raise HTTPException(status_code=404, detail="模组不存在")
        return ModuleMetaResponse(
            id=row.id,
            title=row.title,
            version=row.version,
            authors=row.authors or [],
            players_min=row.players_min,
            players_max=row.players_max,
            difficulty=row.difficulty,
            estimated_duration=row.estimated_duration,
        )
