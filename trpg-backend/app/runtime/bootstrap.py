"""运行时组合根：唯一知道各端口具体实现的模块。"""

from functools import lru_cache

from app.ai.keeper import AgentsSDKKeeper, FakeKeeper
from app.core.config import get_settings
from app.core.db import engine
from app.runtime.engine import ActionExecutor
from app.runtime.orchestrator import TurnOrchestrator
from app.runtime.projector import PlayerViewProjector
from app.runtime.store import SQLAlchemyGameStateStore


@lru_cache
def get_turn_orchestrator() -> TurnOrchestrator:
    settings = get_settings()
    store = SQLAlchemyGameStateStore()
    executor = ActionExecutor(store=store)
    if settings.keeper_provider == "deepseek":
        if not (
            settings.keeper_model
            and settings.keeper_base_url
            and settings.keeper_api_key
        ):
            raise RuntimeError(
                "启用 DeepSeek Keeper 需要 KEEPER_MODEL、KEEPER_BASE_URL、"
                "KEEPER_API_KEY"
            )
        keeper = AgentsSDKKeeper(
            model=settings.keeper_model,
            base_url=settings.keeper_base_url,
            api_key=settings.keeper_api_key,
            engine=engine,
        )
    else:
        keeper = FakeKeeper()
    return TurnOrchestrator(
        store=store,
        executor=executor,
        projector=PlayerViewProjector(),
        keeper=keeper,
    )
