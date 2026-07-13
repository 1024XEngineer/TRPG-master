"""依赖倒置端口：core/rules 定义契约，core/ai 实现并在组合根（server 启动时）注入。

⚠️ 模块拆分设计.md §三"发现的真实依赖"：master §4.5 `SanJudge` 接口注释明确
"仅在没有预设 SanTrigger 命中时由 RulesEngine 调用"——RulesEngine（确定性核心）
运行时真的要调用一个 AI 接口，这跟"领域核心可脱离 AI 独立单测"有张力。

解法：RulesEngine 只依赖这里定义的 `SanJudgePort`（typing.Protocol，结构化类型，
不需要显式继承），不 import core.ai 的具体实现。core.ai.SanJudge 结构上满足
这个 Protocol 即可，真正的接线（注入哪个实现）发生在 server 启动时的组合根。
单测 RulesEngine 时注入一个假的 SanJudgePort 桩即可脱离真实 AI 跑通。
"""

from __future__ import annotations

from typing import Literal, Protocol, Union, runtime_checkable

from pydantic import BaseModel

SanSeverity = Literal["mild", "moderate", "severe", "extreme"]


class SanJudgeNoTrigger(BaseModel):
    trigger: Literal[False] = False


class SanJudgeTriggered(BaseModel):
    trigger: Literal[True] = True
    severity: SanSeverity


SanJudgeResult = Union[SanJudgeNoTrigger, SanJudgeTriggered]


@runtime_checkable
class SanJudgePort(Protocol):
    async def judge(self, scene_text: str) -> SanJudgeResult:
        """`scene_text` 是即将发生的事实（刚揭示的 Entity.content / 刚进入的
        Scene.description），必须在 Narrator 生成最终叙事之前跑，见
        AI编排详细设计 §2.2。
        """
        ...
