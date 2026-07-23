"""服务端权威骰子端口与确定性测试实现。"""

from __future__ import annotations

import random
import re
from collections.abc import Iterable
from typing import Protocol


class DiceRoller(Protocol):
    def d100(self) -> int: ...

    def expression(self, expression: str) -> int: ...


_DICE_EXPRESSION = re.compile(
    r"^\s*(?:(?P<count>\d*)[dD](?P<sides>\d+)|(?P<constant>\d+))"
    r"(?P<modifier>[+-]\d+)?\s*$"
)


class SystemDiceRoller:
    def d100(self) -> int:
        return random.SystemRandom().randint(1, 100)

    def expression(self, expression: str) -> int:
        match = _DICE_EXPRESSION.fullmatch(expression)
        if match is None:
            raise ValueError(f"不支持的骰子表达式：{expression}")
        modifier = int(match.group("modifier") or 0)
        if match.group("constant") is not None:
            return max(0, int(match.group("constant")) + modifier)
        count = int(match.group("count") or 1)
        sides = int(match.group("sides"))
        if not 1 <= count <= 100 or not 2 <= sides <= 1000:
            raise ValueError(f"骰子表达式超出安全范围：{expression}")
        rng = random.SystemRandom()
        return max(0, sum(rng.randint(1, sides) for _ in range(count)) + modifier)


class FixedDiceRoller:
    """测试按顺序消费固定骰值；耗尽时重复最后一个值。"""

    def __init__(self, values: Iterable[int]) -> None:
        self._values = list(values)
        if not self._values:
            raise ValueError("FixedDiceRoller 至少需要一个值")
        self._index = 0

    def _next(self) -> int:
        index = min(self._index, len(self._values) - 1)
        self._index += 1
        return self._values[index]

    def d100(self) -> int:
        value = self._next()
        if not 1 <= value <= 100:
            raise ValueError("固定 d100 结果必须在 1..100")
        return value

    def expression(self, expression: str) -> int:
        match = _DICE_EXPRESSION.fullmatch(expression)
        if match is None:
            raise ValueError(f"不支持的骰子表达式：{expression}")
        modifier = int(match.group("modifier") or 0)
        if match.group("constant") is not None:
            return max(0, int(match.group("constant")) + modifier)
        return max(0, self._next() + modifier)
