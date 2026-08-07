"""Read-only source for A's deterministic PlayerView projector."""

from typing import Protocol

from collaboration_framework.contracts import (
    KeeperCapabilityView,
    PlayerViewScope,
    ProjectionSnapshot,
)


class PlayerViewSource(Protocol):
    async def read(self, scope: PlayerViewScope) -> ProjectionSnapshot: ...

    async def read_keeper_capabilities(
        self,
        scope: PlayerViewScope,
    ) -> KeeperCapabilityView:
        """Controlled Keeper-side capability list bound to the same revision.

        Only the adjudicating Agent consumes it; it never reaches the client or
        the Narrator. See
        :mod:`collaboration_framework.contracts.keeper_view`.
        """
        ...
