from typing import Protocol

from host_orchestrator.schemas.action import ActionRequest, ActionResult


class ActionExecutorPort(Protocol):
    async def execute(self, request: ActionRequest) -> ActionResult: ...
