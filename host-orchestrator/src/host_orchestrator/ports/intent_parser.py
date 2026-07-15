from typing import Protocol

from host_orchestrator.schemas.base import JsonObject
from host_orchestrator.schemas.context import IntentContext


class IntentParserPort(Protocol):
    async def parse(self, context: IntentContext) -> JsonObject: ...
