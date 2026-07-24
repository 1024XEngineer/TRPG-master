"""Read-only source for A's deterministic PlayerView projector."""

from typing import Protocol

from collaboration_framework.contracts import PlayerInput, ProjectionSnapshot


class PlayerViewSource(Protocol):
    async def read(self, player_input: PlayerInput) -> ProjectionSnapshot: ...
