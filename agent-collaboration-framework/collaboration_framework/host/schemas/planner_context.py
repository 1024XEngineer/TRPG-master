"""Framework-independent context for current Host turn planning."""

from __future__ import annotations

from pydantic import model_validator

from collaboration_framework.contracts import (
    ContractModel,
    KeeperCapabilityView,
    PlayerInput,
    PlayerView,
)
from collaboration_framework.host.schemas.history import RecentTurnContext
from collaboration_framework.host.schemas.memory import ConversationSummary, MemoryEntry


def _validate_keeper_scope(
    capabilities: KeeperCapabilityView | None,
    player_view: PlayerView,
) -> None:
    """Keep the player and Keeper views on the same actor and revision."""

    if capabilities is None:
        return
    if capabilities.room_id != player_view.room_id or capabilities.actor_id != player_view.actor_id:
        raise ValueError("KeeperCapabilityView scope 与 PlayerView 不一致")
    if capabilities.revision != player_view.revision:
        raise ValueError("KeeperCapabilityView revision 与 PlayerView 不一致")


class HostAgentContext(ContractModel):
    """Trusted player input paired with the active turn's scoped views."""

    player_input: PlayerInput
    player_view: PlayerView
    recent_history: RecentTurnContext
    memories: tuple[MemoryEntry, ...] = ()
    conversation_summary: ConversationSummary | None = None
    keeper_capabilities: KeeperCapabilityView | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> HostAgentContext:
        mismatches = [
            field_name
            for field_name in ("room_id", "player_id", "actor_id")
            if getattr(self.player_input, field_name) != getattr(self.player_view, field_name)
        ]
        if mismatches:
            raise ValueError("HostAgentContext scope 不一致: " + ", ".join(mismatches))
        _validate_keeper_scope(self.keeper_capabilities, self.player_view)
        self.recent_history.validate_for(
            player_input=self.player_input,
            player_view=self.player_view,
        )
        return self
