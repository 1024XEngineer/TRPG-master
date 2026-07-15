from typing import Protocol

from host_orchestrator.schemas.action import ActionResult
from host_orchestrator.schemas.player_input import PlayerInput
from host_orchestrator.schemas.player_view import PlayerView


class PlayerViewPort(Protocol):
    async def project(self, player_input: PlayerInput) -> PlayerView: ...

    async def refresh(
        self,
        player_input: PlayerInput,
        action_result: ActionResult,
    ) -> PlayerView: ...
