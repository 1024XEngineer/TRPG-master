from typing import Protocol

from host_orchestrator.schemas.base import JsonObject
from host_orchestrator.schemas.context import NarrationContext


class NarratorPort(Protocol):
    async def narrate(self, context: NarrationContext) -> JsonObject: ...
