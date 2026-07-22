"""Safe read contracts used to build the model-visible PlayerView."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from .common import ContractModel


class VisibleFact(ContractModel):
    id: str = Field(min_length=1)
    text: str = Field(min_length=1)


class ProjectionEntity(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    content: str


class ProjectionCheckpointOption(ContractModel):
    id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    action_hint: str = Field(min_length=1)
    skills: tuple[str, ...] = ()


class ProjectionSnapshot(ContractModel):
    """Read-only, GameState-free source consumed by A's projector."""

    room_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    phase: Literal["playing", "ended"]
    revision: str = Field(min_length=1)
    entities: tuple[ProjectionEntity, ...] = ()
    checkpoint_options: tuple[ProjectionCheckpointOption, ...] = ()


class VisibleEntity(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    content: str


class CheckpointOption(ContractModel):
    """Trusted candidate menu exposed to the host semantic matcher."""

    id: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    action_hint: str = Field(min_length=1)
    skills: tuple[str, ...] = ()


class PlayerView(ContractModel):
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    phase: Literal["playing", "ended"]
    revision: str = Field(min_length=1)
    visible_facts: tuple[VisibleFact, ...] = ()
    visible_entities: tuple[VisibleEntity, ...] = ()
    checkpoint_options: tuple[CheckpointOption, ...] = ()
