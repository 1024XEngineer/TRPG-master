"""规则引擎数据库 Adapter 的应用级组合根（issue #121）。"""

from collaboration_framework.engine import RuleEngineService

from app.adapters import SqlAlchemyEngineStore
from app.core.db import async_session_factory

engine_store = SqlAlchemyEngineStore(async_session_factory)
rule_engine_service = RuleEngineService(engine_store)

__all__ = ["engine_store", "rule_engine_service"]
