"""保留追书人旧加载接口，并转发到通用内置模组加载器。"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from collaboration_framework.contracts import ModulePresentation
from sqlalchemy.ext.asyncio import AsyncSession

from app.service.builtin_module_loader import (
    PAPER_CHASE_SPEC,
    BuiltinModuleLoadError,
    BuiltinModuleLoadResult,
    load_builtin_module,
    read_builtin_presentation,
)

PAPER_CHASE_MODULE_ID = PAPER_CHASE_SPEC.module_id
PAPER_CHASE_VERSION = PAPER_CHASE_SPEC.version
PAPER_CHASE_CONTENT_SCHEMA_VERSION = PAPER_CHASE_SPEC.content_schema_version
PAPER_CHASE_WORLD_REF = PAPER_CHASE_SPEC.world_ref
PAPER_CHASE_SOURCE_PATH = PAPER_CHASE_SPEC.source_path

# 兼容既有导入和异常捕获；新代码应使用 BuiltinModule* 名称。
PaperChaseLoadError = BuiltinModuleLoadError
PaperChaseLoadResult = BuiltinModuleLoadResult


def read_paper_chase_presentation() -> ModulePresentation:
    """从当前追书人源路径读取展示数据，保留测试替换路径的能力。"""

    return read_builtin_presentation(
        replace(PAPER_CHASE_SPEC, source_path=Path(PAPER_CHASE_SOURCE_PATH))
    )


async def load_paper_chase(
    db: AsyncSession,
    *,
    _before_commit: Callable[[], None] | None = None,
) -> BuiltinModuleLoadResult:
    """使用通用发布器加载追书人，同时保持旧函数签名。"""

    return await load_builtin_module(
        db,
        replace(PAPER_CHASE_SPEC, source_path=Path(PAPER_CHASE_SOURCE_PATH)),
        _before_commit=_before_commit,
    )
