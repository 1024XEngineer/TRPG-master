"""模组导入解析（离线、异步）——独立于实时回合循环的模块。

🆕 模块拆分设计.md：从 core/ai 独立出来——AI 编排详细设计原文反复强调这是
"离线异步、不进实时回合循环、耦合度远低于核心游戏循环的独立模块"。内部四阶段
管线（骨架粗提取→逐项精提取→关系装配→六步校验）明确推迟到本轮模块拆分之后，
现在只需要粗粒度接口 `ModuleImportAgent.parse()`。
"""

from core.moduleimport.agent import ModuleImportAgent, ModulePackDraft

__all__ = ["ModuleImportAgent", "ModulePackDraft"]
