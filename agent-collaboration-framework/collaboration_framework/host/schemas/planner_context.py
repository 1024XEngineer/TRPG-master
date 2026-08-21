"""Framework-independent context for current Host turn planning."""

from __future__ import annotations

from pydantic import Field, model_validator

from collaboration_framework.contracts import (
    ActionPlanPolicy,
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
    if (
        capabilities.room_id != player_view.room_id
        or capabilities.actor_id != player_view.actor_id
    ):
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
            if getattr(self.player_input, field_name)
            != getattr(self.player_view, field_name)
        ]
        if mismatches:
            raise ValueError("HostAgentContext scope 不一致: " + ", ".join(mismatches))
        _validate_keeper_scope(self.keeper_capabilities, self.player_view)
        self.recent_history.validate_for(
            player_input=self.player_input,
            player_view=self.player_view,
        )
        return self


class TurnPlanningReference(ContractModel):
    """One player-visible label useful for semantic target disambiguation."""

    kind: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=300)
    aliases: tuple[str, ...] = ()


class TurnPlanningView(ContractModel):
    """Token-bounded player-safe projection used only for semantic planning."""

    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    self_name: str = Field(min_length=1)
    current_scene_name: str = Field(min_length=1)
    location_breadcrumbs: tuple[str, ...] = ()
    visible_entities: tuple[TurnPlanningReference, ...] = ()
    visible_actors: tuple[TurnPlanningReference, ...] = ()
    available_destinations: tuple[TurnPlanningReference, ...] = ()
    known_locations: tuple[TurnPlanningReference, ...] = ()
    inventory_items: tuple[TurnPlanningReference, ...] = ()
    known_information: tuple[TurnPlanningReference, ...] = ()

    @classmethod
    def from_player_view(cls, view: PlayerView) -> TurnPlanningView:
        breadcrumbs = (
            tuple(item.name for item in view.location_context.breadcrumbs)
            if view.location_context is not None
            else ()
        )
        destinations = tuple(
            TurnPlanningReference(
                kind="location",
                name=(
                    item.destination.name if item.destination is not None else item.name
                ),
                aliases=item.aliases,
            )
            for item in view.scene.available_exits
        )
        return cls(
            room_id=view.room_id,
            player_id=view.player_id,
            actor_id=view.actor_id,
            revision=view.revision,
            self_name=view.self_actor.name,
            current_scene_name=view.scene.name,
            location_breadcrumbs=breadcrumbs,
            visible_entities=tuple(
                TurnPlanningReference(
                    kind=item.kind, name=item.name, aliases=item.aliases
                )
                for item in view.scene.visible_entities
            ),
            visible_actors=tuple(
                TurnPlanningReference(kind="actor", name=item.name)
                for item in view.scene.visible_actors
            ),
            available_destinations=destinations,
            known_locations=tuple(
                TurnPlanningReference(kind="location", name=item.name)
                for item in view.known_locations
            ),
            inventory_items=tuple(
                TurnPlanningReference(kind="item", name=item.name)
                for item in view.inventory
            ),
            known_information=tuple(
                TurnPlanningReference(kind="information", name=item.title)
                for item in view.known_information
            ),
        )


class TurnPlanningContext(ContractModel):
    """Pure semantic-planning input with no Keeper or adjudication capability data."""

    player_input: PlayerInput
    planning_view: TurnPlanningView
    recent_history: RecentTurnContext
    memories: tuple[MemoryEntry, ...] = ()
    conversation_summary: ConversationSummary | None = None
    policy: ActionPlanPolicy = Field(default_factory=ActionPlanPolicy)

    @model_validator(mode="after")
    def validate_scope(self) -> TurnPlanningContext:
        view = self.planning_view
        mismatches = [
            name
            for name in ("room_id", "player_id", "actor_id")
            if getattr(self.player_input, name) != getattr(view, name)
        ]
        if mismatches:
            raise ValueError(
                "TurnPlanningContext scope 不一致: " + ", ".join(mismatches)
            )
        if (
            self.recent_history.room_id != view.room_id
            or self.recent_history.viewer_player_id != view.player_id
            or self.recent_history.as_of_revision != view.revision
        ):
            raise ValueError("TurnPlanningContext recent_history scope 不一致")
        if any(item.room_id != view.room_id for item in self.memories):
            raise ValueError("TurnPlanningContext memory scope 不一致")
        if self.conversation_summary is not None and (
            self.conversation_summary.room_id != view.room_id
            or self.conversation_summary.player_id != view.player_id
        ):
            raise ValueError("TurnPlanningContext conversation summary scope 不一致")
        return self
