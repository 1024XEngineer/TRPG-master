"""Untrusted structured-output source for the authoritative game opening."""

from typing import Protocol

from collaboration_framework.contracts import JsonObject
from collaboration_framework.host.schemas import OpeningNarrationContext


class OpeningNarrationModelPort(Protocol):
    async def generate(self, context: OpeningNarrationContext) -> JsonObject: ...
