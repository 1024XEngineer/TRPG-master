from host_orchestrator.schemas.base import JsonObject
from host_orchestrator.schemas.context import NarrationContext


class FakeNarrator:
    """TODO: contract-only fake; no model or prompt implementation."""

    async def narrate(self, context: NarrationContext) -> JsonObject:
        raise NotImplementedError("TODO: provide a contract fixture")
