from host_orchestrator.schemas.base import JsonObject
from host_orchestrator.schemas.context import IntentContext


class FakeIntentParser:
    """TODO: contract-only fake; no model or prompt implementation."""

    async def parse(self, context: IntentContext) -> JsonObject:
        raise NotImplementedError("TODO: provide a contract fixture")
