"""The only host command that may cause authoritative game-state effects."""

from typing import Protocol

from collaboration_framework.contracts import ActionRequest, ActionResult


class ActionExecutor(Protocol):
    async def execute(self, request: ActionRequest) -> ActionResult: ...
