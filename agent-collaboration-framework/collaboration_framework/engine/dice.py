"""Server-authoritative dice and COC7 percentile resolution."""

from __future__ import annotations

import re
import hashlib
import hmac
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
        self._values = tuple(values)
        self._index = 0

    def randint(self, minimum: int, maximum: int) -> int:
        if self._index >= len(self._values):
            raise AssertionError("Deterministic dice sequence exhausted")
        value = self._values[self._index]
        self._index += 1
        if not minimum <= value <= maximum:
            raise AssertionError(
                f"Deterministic roll {value} is outside [{minimum}, {maximum}]"
            )
        return value

    def recovery_snapshot(self):
        return {"kind": "sequence", "values": list(self._values[self._index :])}


class SeededDiceSource:
    """Versioned HMAC counter stream with rejection sampling, private to a command."""

    def __init__(self, seed: str):
        self._seed = bytes.fromhex(seed)
        self._counter = 0

    def randint(self, minimum: int, maximum: int) -> int:
        size = maximum - minimum + 1
        if size < 1:
            raise ValueError("invalid dice bounds")
        limit = (1 << 256) - ((1 << 256) % size)
        while True:
            value = int.from_bytes(
                hmac.new(
                    self._seed, str(self._counter).encode(), hashlib.sha256
                ).digest()
            )
            self._counter += 1
            if value < limit:
                return minimum + value % size


class FixedDiceSource:
    """Test-only source, serializable for fault/restart tests."""

    def __init__(self, value: int):
        self.value = value

    def randint(self, minimum: int, maximum: int) -> int:
        if not minimum <= self.value <= maximum:
            raise AssertionError(
                f"Fixed test roll {self.value} is outside [{minimum}, {maximum}]"
            )
        return self.value

    def recovery_snapshot(self):
        return {"kind": "fixed", "value": self.value}


class SidesSequenceDiceSource:
    """Finite test queues keyed by die size, configured only at the test composition root."""

    def __init__(self, values):
        self._sources = {
            int(sides): SequenceDiceSource(rolls) for sides, rolls in values.items()
        }
        for sides, source in self._sources.items():
            if sides < 2 or any(
                type(value) is not int or not 1 <= value <= sides
                for value in source._values
            ):
                raise ValueError("Invalid test dice queue")

    def randint(self, minimum, maximum):
        if minimum != 1 or maximum not in self._sources:
            raise AssertionError(f"No deterministic queue for [{minimum}, {maximum}]")
        return self._sources[maximum].randint(minimum, maximum)

    def recovery_snapshot(self):
        return {
            "kind": "by_sides",
            "values": {
                str(sides): source.recovery_snapshot()["values"]
                for sides, source in self._sources.items()
            },
        }


_DICE_EXPRESSION = re.compile(
    r"^\s*(?P<count>\d+)[dD](?P<sides>\d+)(?P<modifier>[+-]\d+)?\s*$"
)


class DiceRoller:
    def __init__(self, source: DiceSource | None = None) -> None:
        self._source = source or SystemDiceSource()

    def recovery_snapshot(self):
        if isinstance(self._source, SystemDiceSource):
            return {"kind": "hmac-sha256-v1", "seed": secrets.token_hex(32)}
        snapshot = getattr(self._source, "recovery_snapshot", None)
        if snapshot is None:
            raise ContractError("Dice source does not support recovery snapshots")
        return snapshot()

    def for_recovery(self, snapshot, *, fresh=False):
        kind = snapshot["kind"]
        if kind == "hmac-sha256-v1":
            return DiceRoller(SeededDiceSource(snapshot["seed"]))
        if fresh:
            # Keep existing finite-sequence test semantics across commands.
            return self
        if kind == "sequence":
            return DiceRoller(SequenceDiceSource(snapshot["values"]))
        if kind == "by_sides":
            return DiceRoller(SidesSequenceDiceSource(snapshot["values"]))
        if kind == "fixed":
            return DiceRoller(FixedDiceSource(snapshot["value"]))
        raise ContractError("Unknown dice recovery format")

    def percentile(self) -> int:
        return self._source.randint(1, 100)

    def quantity(self, quantity):
        """Return a closed quantity and the individual authoritative dice."""
        from collaboration_framework.contracts.resources import FixedQuantity

        if isinstance(quantity, FixedQuantity):
            return quantity.value, ()
        rolls = tuple(
            self._source.randint(1, quantity.sides) for _ in range(quantity.count)
        )
        return sum(rolls) + quantity.bonus, rolls

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
