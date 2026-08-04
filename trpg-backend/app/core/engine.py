"""规则引擎数据库 Adapter 的应用级组合根（issue #121）。"""

from collaboration_framework.engine import (
    AdjudicationEngineService,
    RuleEngineService,
    RuleKernel,
)

from app.adapters import SqlAlchemyEngineStore
from app.core.db import async_session_factory

engine_store = SqlAlchemyEngineStore(async_session_factory)
adjudication_engine_service = AdjudicationEngineService(engine_store)
rule_engine_service = RuleEngineService(
    engine_store,
    kernel=RuleKernel(allow_legacy_missing_skill=False),
)

__all__ = [
    "adjudication_engine_service",
    "engine_store",
    "rule_engine_service",
]
