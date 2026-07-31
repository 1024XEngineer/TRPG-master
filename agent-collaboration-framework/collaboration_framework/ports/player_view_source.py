"""Read-only source for A's deterministic PlayerView projector."""

from typing import Protocol

from collaboration_framework.contracts import PlayerViewScope, ProjectionSnapshot


class PlayerViewSource(Protocol):
    async def read(self, scope: PlayerViewScope) -> ProjectionSnapshot: ...
