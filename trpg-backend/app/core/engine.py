"""规则引擎数据库 Adapter 的应用级组合根（issue #121）。"""

from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    RuleEngineService,
    RuleKernel,
)

from app.adapters import SqlAlchemyActionPlanRunStore, SqlAlchemyEngineStore
from app.core.config import get_settings
from app.core.db import async_session_factory


class _FixedDiceSource:
    def __init__(self, value: int) -> None:
        self._value = value

    def randint(self, minimum: int, maximum: int) -> int:
        if not minimum <= self._value <= maximum:
            raise AssertionError(f"Fixed test roll {self._value} is outside [{minimum}, {maximum}]")
        return self._value


engine_store = SqlAlchemyEngineStore(async_session_factory)
action_plan_store = SqlAlchemyActionPlanRunStore(async_session_factory)
_settings = get_settings()
_dice = (
    DiceRoller(_FixedDiceSource(_settings.test_fixed_dice_roll))
    if _settings.app_env == "test" and _settings.test_fixed_dice_roll is not None
    else None
)
adjudication_engine_service = AdjudicationEngineService(engine_store, dice=_dice)
rule_engine_service = RuleEngineService(
    engine_store,
    kernel=RuleKernel(allow_legacy_missing_skill=False),
)

__all__ = [
    "adjudication_engine_service",
    "action_plan_store",
    "engine_store",
    "rule_engine_service",
]
