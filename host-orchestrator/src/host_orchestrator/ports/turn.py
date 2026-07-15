from typing import Protocol

from host_orchestrator.schemas.output import TurnOutput
from host_orchestrator.schemas.player_input import PlayerInput


class TurnPort(Protocol):
    async def run(self, player_input: PlayerInput) -> TurnOutput: ...
