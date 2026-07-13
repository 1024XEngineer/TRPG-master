"""ModuleImportAgent —— 粗粒度接口（内部管线推迟到本轮之后，见 AI编排详细设计待办）。

对应 module_import_jobs 表状态机（queued/parsing/validating/failed/succeeded），
产出经六步校验（master §4.3.3）后才真正落进 ContentRepo 管的表。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from core.content.models import ModulePack


class ModulePackDraft(BaseModel):
    """LLM/Agent 解析原始材料后产出的候选内容，尚未通过六步校验，不等于 ModulePack。"""

    raw_source_ref: str
    draft: dict  # 未校验的候选结构，校验通过后才转换成 ModulePack


@runtime_checkable
class ModuleImportAgent(Protocol):
    async def parse(self, raw_source_ref: str) -> ModulePackDraft:
        """粗粒度入口——内部分阶段管线（骨架粗提取→逐项精提取→关系装配）
        推迟到本轮模块拆分之后细化。
        """
        ...

    async def validate_and_ingest(self, draft: ModulePackDraft) -> ModulePack:
        """走 master §4.3.3 六步校验，通过后入库；对应 module_import_jobs.status
        从 'validating' 转 'succeeded'/'failed'。
        """
        ...


class StubModuleImportAgent:
    async def parse(self, raw_source_ref: str) -> ModulePackDraft:
        raise NotImplementedError("ModuleImportAgent.parse: 内部管线待模块拆分后细化")

    async def validate_and_ingest(self, draft: ModulePackDraft) -> ModulePack:
        raise NotImplementedError("ModuleImportAgent.validate_and_ingest: 待实现六步校验")
