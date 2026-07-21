"""Member-B internal state, Event, and execution-result models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from collaboration_framework.contracts import ActionResult, ContractModel


class ActorState(ContractModel):
    player_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_character_id: str = Field(min_length=1)
    source_character_version: int = Field(ge=1)
    state: dict[str, JsonValue] = Field(default_factory=dict)


class GameState(ContractModel):
    """Authoritative state shape used only by the fake engine."""

    room_id: str
    scene_id: str
    phase: Literal["playing", "ended"] = "playing"
    ending_id: str | None = None
    event_sequence: int = Field(default=0, ge=0)
    actors: dict[str, ActorState]
    entities: dict[str, dict[str, JsonValue]]


class StateChange(ContractModel):
    path: str
    from_value: JsonValue = Field(alias="from")
    to: JsonValue
    cause: str


class StateModifiedPayload(ContractModel):
    path: str = Field(min_length=1)
    from_value: JsonValue = Field(alias="from")
    to: JsonValue


class StateModifiedEvent(ContractModel):
    event_id: str
    sequence: int = Field(ge=1)
    type: Literal["state.modified"] = "state.modified"
    room_id: str
    actor_id: str
    client_action_id: str
    cause: str
    visibility: Literal["public", "private", "hidden"] = "public"
    payload: StateModifiedPayload


class EngineExecutionResult(ContractModel):
    """Internal result retained by B; only action_result crosses into A."""

    action_result: ActionResult
    confirmed_facts: tuple[str, ...] = ()
    state_changes: tuple[StateChange, ...] = ()
    events: tuple[StateModifiedEvent, ...] = ()
    state_version: int = Field(ge=0)
