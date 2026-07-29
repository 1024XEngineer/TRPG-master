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


class ProjectionNarrativeDetail(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal[
        "description",
        "sensory",
        "atmosphere",
        "pacing",
        "foreshadowing",
    ]
    text: str = Field(min_length=1)


class ProjectionEntity(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    description: str
    narrative_details: tuple[ProjectionNarrativeDetail, ...] = ()
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
    narrative_details: tuple[ProjectionNarrativeDetail, ...] = ()
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


class ProjectionActionDeclarationOption(ContractModel):
    id: str = Field(min_length=1)
    semantic_hints: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_semantic_hints(self) -> ProjectionActionDeclarationOption:
        _validate_semantic_hints(self.semantic_hints)
        return self


class ProjectionCheckpointOption(ContractModel):
    id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    action_hint: str = Field(min_length=1)
    skills: tuple[str, ...] = ()
    difficulty: Literal["regular", "hard", "extreme"] | None = None
    declaration_options: tuple[ProjectionActionDeclarationOption, ...] = ()

    @model_validator(mode="after")
    def validate_declaration_options(self) -> ProjectionCheckpointOption:
        _validate_declaration_option_ids(self.declaration_options)
        return self


class ProjectionSnapshot(ContractModel):
    """Read-only, GameState-free source consumed by A's projector."""

    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    background: str = Field(min_length=1)
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


class NarrativeDetailView(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal[
        "description",
        "sensory",
        "atmosphere",
        "pacing",
        "foreshadowing",
    ]
    text: str = Field(min_length=1)


class VisibleEntity(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    description: str
    narrative_details: tuple[NarrativeDetailView, ...] = ()
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
    narrative_details: tuple[NarrativeDetailView, ...] = ()
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


class ActionDeclarationOption(ContractModel):
    """Player-safe declaration id and semantic cues supplied by one checkpoint."""

    id: str = Field(min_length=1)
    semantic_hints: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_semantic_hints(self) -> ActionDeclarationOption:
        _validate_semantic_hints(self.semantic_hints)
        return self


class CheckpointOption(ContractModel):
    """Trusted candidate menu exposed to the host semantic matcher."""

    id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    action_hint: str = Field(min_length=1)
    skills: tuple[str, ...] = ()
    difficulty: Literal["regular", "hard", "extreme"] | None = None
    declaration_options: tuple[ActionDeclarationOption, ...] = ()

    @model_validator(mode="after")
    def validate_declaration_options(self) -> CheckpointOption:
        _validate_declaration_option_ids(self.declaration_options)
        return self


class PlayerView(ContractModel):
    """Complete player-safe world snapshot used by one model/Agent run."""

    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    background: str = Field(min_length=1)
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


def _validate_semantic_hints(hints: tuple[str, ...]) -> None:
    normalized = [item.strip().casefold() for item in hints]
    if any(not item for item in normalized):
        raise ValueError("Action declaration semantic_hints 不得为空")
    if len(normalized) != len(set(normalized)):
        raise ValueError("Action declaration semantic_hints 必须唯一")


def _validate_declaration_option_ids(options: tuple[object, ...]) -> None:
    ids = [getattr(item, "id", None) for item in options]
    if len(ids) != len(set(ids)):
        raise ValueError("Checkpoint declaration option id 必须唯一")
