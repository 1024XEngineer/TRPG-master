from typing import Protocol

from collaboration_framework.contracts import PlayerInput
from collaboration_framework.host.schemas import TurnOutput


class TurnPort(Protocol):
    async def run(self, player_input: PlayerInput) -> TurnOutput: ...
