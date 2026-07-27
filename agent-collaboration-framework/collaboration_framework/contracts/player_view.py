"""Revision-bound player-safe projection and model-view contracts."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from .common import ContractModel


class VisibleFact(ContractModel):
    """One fact confirmed for the current action result."""

    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ProjectionActorValue(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    value: int | float


class ProjectionActorResource(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    value: int


class ProjectionSelfActor(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    occupation: str | None = None
    attributes: tuple[ProjectionActorValue, ...] = ()
    skills: tuple[ProjectionActorValue, ...] = ()
    resources: tuple[ProjectionActorResource, ...] = ()
    conditions: tuple[str, ...] = ()
    equipment: tuple[str, ...] = ()
    background_summary: str = ""


class ProjectionVisibleActor(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status_summary: str = ""


class ProjectionObservableState(ContractModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: JsonValue


class ProjectionEntity(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    description: str
    observable_state: tuple[ProjectionObservableState, ...] = ()


class ProjectionExitDestination(ContractModel):
    scene_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class ProjectionAvailableExit(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    description: str = ""
    destination: ProjectionExitDestination | None = None


class ProjectionScene(ContractModel):
    id: str = Field(min_length=1)
    name: str
    description: str
    time: str | None = None
    visible_entities: tuple[ProjectionEntity, ...] = ()
    visible_actors: tuple[ProjectionVisibleActor, ...] = ()
    available_exits: tuple[ProjectionAvailableExit, ...] = ()


class ProjectionKnownInformation(ContractModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    content: str = Field(min_length=1)
    related_entities: tuple[str, ...] = ()
    related_scenes: tuple[str, ...] = ()
    scope: Literal["actor", "party"]


class ProjectionCheckpointOption(ContractModel):
    id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    action_hint: str = Field(min_length=1)
    skills: tuple[str, ...] = ()
    difficulty: Literal["regular", "hard", "extreme"] | None = None


class ProjectionSnapshot(ContractModel):
    """Read-only, GameState-free source consumed by A's projector."""

    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    phase: Literal["playing", "ended"]
    revision: str = Field(min_length=1)
    self_actor: ProjectionSelfActor
    scene: ProjectionScene
    known_information: tuple[ProjectionKnownInformation, ...] = ()
    checkpoint_options: tuple[ProjectionCheckpointOption, ...] = ()

    @property
    def visible_facts(self) -> tuple[VisibleFact, ...]:
        """Compatibility view for callers migrating to structured known information."""

        return tuple(
            VisibleFact(id=item.id, text=item.content) for item in self.known_information
        )

    @model_validator(mode="after")
    def validate_revision_scope(self) -> ProjectionSnapshot:
        if self.self_actor.id != self.actor_id or self.scene.id != self.scene_id:
            raise ValueError("ProjectionSnapshot actor/scene scope 不一致")
        return self


class ActorValueView(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    value: int | float


class ActorResourceView(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    value: int


class SelfActorView(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    occupation: str | None = None
    attributes: tuple[ActorValueView, ...] = ()
    skills: tuple[ActorValueView, ...] = ()
    resources: tuple[ActorResourceView, ...] = ()
    conditions: tuple[str, ...] = ()
    equipment: tuple[str, ...] = ()
    background_summary: str = ""


class VisibleActorView(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    status_summary: str = ""


class ObservableStateView(ContractModel):
    key: str = Field(min_length=1)
    label: str = Field(min_length=1)
    value: JsonValue


class VisibleEntity(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    description: str
    observable_state: tuple[ObservableStateView, ...] = ()


class ExitDestinationView(ContractModel):
    scene_id: str = Field(min_length=1)
    name: str = Field(min_length=1)


class AvailableExitView(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    description: str = ""
    destination: ExitDestinationView | None = None


class SceneView(ContractModel):
    id: str = Field(min_length=1)
    name: str
    description: str
    time: str | None = None
    visible_entities: tuple[VisibleEntity, ...] = ()
    visible_actors: tuple[VisibleActorView, ...] = ()
    available_exits: tuple[AvailableExitView, ...] = ()


class KnownInformationView(ContractModel):
    id: str = Field(min_length=1)
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    content: str = Field(min_length=1)
    related_entities: tuple[str, ...] = ()
    related_scenes: tuple[str, ...] = ()
    scope: Literal["actor", "party"]


class CheckpointOption(ContractModel):
    """Trusted candidate menu exposed to the host semantic matcher."""

    id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    action_hint: str = Field(min_length=1)
    skills: tuple[str, ...] = ()
    difficulty: Literal["regular", "hard", "extreme"] | None = None


class PlayerView(ContractModel):
    """Complete player-safe world snapshot used by one model/Agent run."""

    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    phase: Literal["playing", "ended"]
    revision: str = Field(min_length=1)
    self_actor: SelfActorView
    scene: SceneView
    known_information: tuple[KnownInformationView, ...] = ()
    checkpoint_options: tuple[CheckpointOption, ...] = ()

    @property
    def visible_facts(self) -> tuple[VisibleFact, ...]:
        """Compatibility view for callers migrating to structured known information."""

        return tuple(
            VisibleFact(id=item.id, text=item.content) for item in self.known_information
        )

    @model_validator(mode="after")
    def validate_revision_scope(self) -> PlayerView:
        if self.self_actor.id != self.actor_id or self.scene.id != self.scene_id:
            raise ValueError("PlayerView actor/scene scope 不一致")
        return self
