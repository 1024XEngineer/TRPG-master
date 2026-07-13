"""SanJudge —— 对应 master §4.5 + AI编排详细设计 §2.2。

结构上实现 core.rules.ports.SanJudgePort（typing.Protocol，鸭子类型，不需要
显式继承）——仅在没有预设 SanTrigger 命中时由 RulesEngine 调用，severity
查 World.sanityMechanic.severityTable 换算成确定性 SanLossSpec，不产出
flat/direct/max_reduce/gain/capped 这类更强的效果（见该文档 §2.2 边界说明）。
"""

from __future__ import annotations

from core.rules.ports import SanJudgeResult


class SanJudge:
    """满足 core.rules.ports.SanJudgePort 的具体实现——LLM，role 见 core.ai.config。"""

    async def judge(self, scene_text: str) -> SanJudgeResult:
        raise NotImplementedError("SanJudge.judge: 待接入 LLM（role='narrator'，临场触发用途）")
