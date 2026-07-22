"""Untrusted structured-output source for Narrator."""

from typing import Protocol

from collaboration_framework.contracts import JsonObject
from collaboration_framework.host.schemas import NarrationContext


class NarrationModelPort(Protocol):
    async def generate(self, context: NarrationContext) -> JsonObject: ...
