"""Untrusted structured-output source for IntentParser."""

from typing import Protocol

from collaboration_framework.contracts import JsonObject
from collaboration_framework.host.schemas import IntentContext


class IntentModelPort(Protocol):
    async def generate(self, context: IntentContext) -> JsonObject: ...
