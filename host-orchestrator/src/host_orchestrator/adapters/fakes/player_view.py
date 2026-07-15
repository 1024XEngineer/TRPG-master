from host_orchestrator.schemas.action import ActionResult
from host_orchestrator.schemas.player_input import PlayerInput
from host_orchestrator.schemas.player_view import PlayerView


class FakePlayerView:
    """TODO: contract-only fake for orchestration-owned player projection."""

    async def project(self, player_input: PlayerInput) -> PlayerView:
        raise NotImplementedError("TODO: provide a contract fixture")

    async def refresh(
        self,
        player_input: PlayerInput,
        action_result: ActionResult,
    ) -> PlayerView:
        raise NotImplementedError("TODO: provide a contract fixture")
