"""Server-authoritative dice and COC7 percentile resolution."""

from __future__ import annotations

import re
import secrets
from collections.abc import Iterable
from typing import Literal, Protocol, TypeAlias

from collaboration_framework.contracts import ContractError

CheckOutcomeName: TypeAlias = Literal[
    "success",
    "failure",
    "critical_success",
    "extreme_success",
    "hard_success",
    "regular_success",
    "fumble",
]
SuccessLevel: TypeAlias = Literal[
    "critical",
    "extreme",
    "hard",
    "regular",
    "failure",
    "fumble",
]
Difficulty: TypeAlias = Literal["regular", "hard", "extreme"]


class DiceSource(Protocol):
    def randint(self, minimum: int, maximum: int) -> int: ...


class SystemDiceSource:
    """Unbiased process-local source used by production kernels."""

    def randint(self, minimum: int, maximum: int) -> int:
        if minimum > maximum:
            raise ValueError("minimum cannot exceed maximum")
        return minimum + secrets.randbelow(maximum - minimum + 1)


class SequenceDiceSource:
    """Deterministic finite source for rule and integration tests."""

    def __init__(self, values: Iterable[int]) -> None:
        self._values = iter(values)

    def randint(self, minimum: int, maximum: int) -> int:
        try:
            value = next(self._values)
        except StopIteration as exc:
            raise AssertionError("Deterministic dice sequence exhausted") from exc
        if not minimum <= value <= maximum:
            raise AssertionError(
                f"Deterministic roll {value} is outside [{minimum}, {maximum}]"
            )
        return value


_DICE_EXPRESSION = re.compile(
    r"^\s*(?P<count>\d+)[dD](?P<sides>\d+)(?P<modifier>[+-]\d+)?\s*$"
)


class DiceRoller:
    def __init__(self, source: DiceSource | None = None) -> None:
        self._source = source or SystemDiceSource()

    def percentile(self) -> int:
        return self._source.randint(1, 100)

    def roll(self, expression: str) -> int:
        if expression.strip().lstrip("+-").isdigit():
            return int(expression)
        match = _DICE_EXPRESSION.fullmatch(expression)
        if match is None:
            raise ContractError(f"Unsupported dice expression: {expression}")
        count = int(match.group("count"))
        sides = int(match.group("sides"))
        modifier = int(match.group("modifier") or 0)
        if not 1 <= count <= 100 or not 2 <= sides <= 1000:
            raise ContractError(
                f"Dice expression is outside runtime limits: {expression}"
            )
        return sum(self._source.randint(1, sides) for _ in range(count)) + modifier


def coc7_success_level(target: int, roll: int) -> SuccessLevel:
    if not 0 <= target <= 100:
        raise ContractError(f"COC7 target is outside [0, 100]: {target}")
    if not 1 <= roll <= 100:
        raise ContractError(f"COC7 percentile roll is outside [1, 100]: {roll}")
    if roll == 1:
        return "critical"
    fumble_threshold = 96 if target < 50 else 100
    if roll >= fumble_threshold:
        return "fumble"
    if roll <= target // 5:
        return "extreme"
    if roll <= target // 2:
        return "hard"
    if roll <= target:
        return "regular"
    return "failure"


def passes_difficulty(level: SuccessLevel, difficulty: Difficulty) -> bool:
    ranks = {
        "fumble": 0,
        "failure": 0,
        "regular": 1,
        "hard": 2,
        "extreme": 3,
        "critical": 4,
    }
    required = {"regular": 1, "hard": 2, "extreme": 3}
    return ranks[level] >= required[difficulty]


def outcome_name(level: SuccessLevel, *, passed: bool) -> CheckOutcomeName:
    if level == "fumble":
        return "fumble"
    if not passed:
        return "failure"
    success_outcomes: dict[SuccessLevel, CheckOutcomeName] = {
        "critical": "critical_success",
        "extreme": "extreme_success",
        "hard": "hard_success",
        "regular": "regular_success",
        "failure": "failure",
        "fumble": "fumble",
    }
    return success_outcomes[level]
