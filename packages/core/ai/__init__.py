"""L5 AI 适配层（实时角色）——对应 master §4.5/§6.3 + AI 编排架构详细设计。

模块拆分设计.md 二次修订：内部按文件组织（不再拆子包），六个角色体量都不大。
2026-07-12 起不再有单独的 ModelAdapter 接口——各角色接口内部自行按 role 查
ModelRoleConfig 选供应商/型号调用（见 config.py），master §6.3 已同步。
"""

from core.ai.adapters import ImageGenAdapter, STTAdapter
from core.ai.config import ModelRole, ModelRoleConfig
from core.ai.intent import IntentParser
from core.ai.narrator import Narrator, Persona
from core.ai.qa import QAResponder
from core.ai.san_judge import SanJudge
from core.ai.summary import RoomSummary, SummaryGenerator

__all__ = [
    "ImageGenAdapter",
    "STTAdapter",
    "ModelRole",
    "ModelRoleConfig",
    "IntentParser",
    "Narrator",
    "Persona",
    "QAResponder",
    "SanJudge",
    "RoomSummary",
    "SummaryGenerator",
]
