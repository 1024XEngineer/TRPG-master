"""L4 领域核心·确定性（系统心脏）——对应 master §4.5/§4.3.6，动作裁决与检定。

领域核心可脱离 AI 与网络独立单测（master §二末尾）。RulesEngine 运行时需要
在没有预设 SanTrigger 命中时判断 SAN 是否临场触发（AI 编排详细设计 §2.2），
这条依赖用本包定义的 SanJudgePort 接口承接（依赖倒置）——core/ai.SanJudge
实现这个 Protocol 并在启动时注入，本包不 import core.ai，见 ports.py。
"""

from core.rules.check_resolver import CheckResolver
from core.rules.engine import RulesEngine
from core.rules.models import ActionResult, CheckRollResult, Intent, Ref, ResolutionKind
from core.rules.ports import SanJudgePort, SanSeverity

__all__ = [
    "CheckResolver",
    "RulesEngine",
    "ActionResult",
    "CheckRollResult",
    "Intent",
    "Ref",
    "ResolutionKind",
    "SanJudgePort",
    "SanSeverity",
]
