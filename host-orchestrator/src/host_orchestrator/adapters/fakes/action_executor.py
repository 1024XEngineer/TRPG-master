from host_orchestrator.schemas.action import ActionRequest, ActionResult


class FakeActionExecutor:
    """TODO: contract-only fake; never owns or mutates GameState."""

    async def execute(self, request: ActionRequest) -> ActionResult:
        raise NotImplementedError("TODO: provide a contract fixture")
