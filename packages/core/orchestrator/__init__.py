"""L3 编排层——对应 master §4.5 Orchestrator，一回合的总指挥。

这是本次骨架里**真正把各模块串联起来**的地方——handle_turn 的方法体不是
NotImplementedError 桩，而是按 master §2.1/§三 时序真实依次调用
IntentParser → RulesEngine → ViewProjector → Narrator，只是每个被调用者
自己的内部实现是桩（会在真正跑起来时抛 NotImplementedError）。
"""

from core.orchestrator.orchestrator import Orchestrator

__all__ = ["Orchestrator"]
