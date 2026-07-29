"""Read-only source for revision-bound player-safe recent history."""

from typing import Protocol, runtime_checkable

from collaboration_framework.contracts import PlayerInput, PlayerView
from collaboration_framework.host.schemas.history import (
    RecentHistoryBudget,
    RecentTurnContext,
)


@runtime_checkable
class RecentHistorySource(Protocol):
    async def read(
        self,
        *,
        player_input: PlayerInput,
        player_view: PlayerView,
        exclude_correlation_id: str,
        budget: RecentHistoryBudget,
    ) -> RecentTurnContext: ...
