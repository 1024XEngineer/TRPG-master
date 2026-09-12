"""规则引擎数据库 Adapter 的应用级组合根（issue #121）。"""

from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    RuleEngineService,
)
from collaboration_framework.engine.dice import FixedDiceSource as _FixedDiceSource
from collaboration_framework.engine.dice import SidesSequenceDiceSource

from app.adapters import SqlAlchemyActionPlanRunStore, SqlAlchemyEngineStore
from app.core.config import get_settings
from app.core.db import async_session_factory
from app.core.legacy_turn_run import LegacySingleActionRecoveryAdapter

engine_store = SqlAlchemyEngineStore(async_session_factory)
action_plan_store = SqlAlchemyActionPlanRunStore(async_session_factory)
_settings = get_settings()
_dice = (
    DiceRoller(_FixedDiceSource(_settings.test_fixed_dice_roll))
    if _settings.app_env == "test" and _settings.test_fixed_dice_roll is not None
    else None
)
if _settings.app_env == "test" and _settings.test_dice_by_sides is not None:
    _dice = DiceRoller(SidesSequenceDiceSource(_settings.test_dice_by_sides))
adjudication_engine_service = AdjudicationEngineService(engine_store, dice=_dice)
rule_engine_service = RuleEngineService(engine_store)
legacy_single_action_recovery = LegacySingleActionRecoveryAdapter(
    engine=adjudication_engine_service,
    session_factory=async_session_factory,
)

__all__ = [
    "adjudication_engine_service",
    "action_plan_store",
    "engine_store",
    "rule_engine_service",
    "legacy_single_action_recovery",
]
