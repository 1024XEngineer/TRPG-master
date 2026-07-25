"""Member-B internal state, Event, and execution-result models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from collaboration_framework.contracts import (
    ActionRequest,
    ActionResult,
    ContractModel,
    ModuleContent,
)


class ActorResources(ContractModel):
    """Mutable in-session resources, detached from the source character sheet."""

    hp: int | None = None
    san: int | None = Field(default=None, ge=0)
    mp: int | None = Field(default=None, ge=0)
    luck: int | None = Field(default=None, ge=0)
    mythos: int = Field(default=0, ge=0)


class ActorState(ContractModel):
    player_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    source_character_id: str = Field(min_length=1)
    source_character_version: int = Field(ge=1)
    state: dict[str, JsonValue] = Field(default_factory=dict)
    resources: ActorResources = Field(default_factory=ActorResources)
    conditions: tuple[str, ...] = ()


class ClockState(ContractModel):
    """Small deterministic clock used by module expressions and time hooks."""

    elapsed_minutes: int = Field(default=0, ge=0)
    time_of_day: Literal["day", "night"] = "day"
    turn: int = Field(default=0, ge=0)


class GameState(ContractModel):
    """Authoritative room state loaded and committed only through EngineStore."""

    room_id: str
    scene_id: str
    phase: Literal["playing", "ended"] = "playing"
    ending_id: str | None = None
    event_sequence: int = Field(default=0, ge=0)
    actors: dict[str, ActorState]
    entities: dict[str, dict[str, JsonValue]]
    clock: ClockState = Field(default_factory=ClockState)
    discovered_facts: tuple[str, ...] = ()


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


class EngineRuntimeSnapshot(ContractModel):
    """Deep-copied authoritative inputs loaded for one room transaction."""

    module_id: str = Field(min_length=1)
    module_version: str = Field(min_length=1)
    module_content: ModuleContent
    game_state: GameState
    revision: str = Field(min_length=1)


class CompletedAction(ContractModel):
    """Original command and semantic result retained for idempotent replay."""

    request: ActionRequest
    execution: EngineExecutionResult
