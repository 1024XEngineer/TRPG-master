"""CheckResolver —— 对应 master §4.5 `interface CheckResolver`。

d100 检定（可配置、支持暗骰）。骰子结果一律服务端权威计算（2026-07-11 新增
原则，见 API 对齐规范 §2.6），此接口就是那条原则的落点。
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from core.rules.models import CheckRollResult


@runtime_checkable
class CheckResolver(Protocol):
    def roll(self, skill: str, target: int, hidden: bool) -> CheckRollResult:
        ...


class StubCheckResolver:
    def roll(self, skill: str, target: int, hidden: bool) -> CheckRollResult:
        raise NotImplementedError("CheckResolver.roll: 待接入真实 d100 掷骰实现")
