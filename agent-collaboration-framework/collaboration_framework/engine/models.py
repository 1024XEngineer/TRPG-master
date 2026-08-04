"""Member-B internal state, Event, and execution-result models."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionRequest,
    ActionResult,
    AdjudicationExecution,
    CheckDecisionRequest,
    ContractModel,
    ModuleContent,
    PendingCheckDecisionView,
    PendingCheckOption,
    PostRollDecisionRequest,
    PostRollOption,
    SubmitAdjudicationRequest,
)
from collaboration_framework.contracts.adjudication import CheckRoll


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
    actor_discovered_facts: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    runtime_locations: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    runtime_entities: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    visibility_overrides: dict[str, bool] = Field(default_factory=dict)
    core_resolved: bool = False
    ending_available: bool = False


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


class DomainEvent(ContractModel):
    """Append-only v3 event; provisional check events carry no gameplay effects."""

    event_id: str = Field(min_length=1)
    sequence: int = Field(ge=1)
    type: str = Field(min_length=1)
    room_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    client_action_id: str = Field(min_length=1)
    cause: str = Field(min_length=1)
    visibility: Literal["public", "private", "hidden"] = "public"
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class PendingCheckDecision(ContractModel):
    decision_id: str = Field(min_length=1)
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    action_request_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    decision_version: int = Field(default=1, ge=1)
    status: Literal["awaiting_skill_choice", "rolled", "resolved", "cancelled"]
    adjudication: ActionAdjudication
    options: tuple[PendingCheckOption, ...] = Field(min_length=1)

    def player_view(self) -> PendingCheckDecisionView:
        if self.status != "awaiting_skill_choice":
            raise ValueError("只有 awaiting_skill_choice 决策可以投影为待选择视图")
        return PendingCheckDecisionView(
            decision_id=self.decision_id,
            action_request_id=self.action_request_id,
            source_revision=self.source_revision,
            decision_version=self.decision_version,
            actor_id=self.actor_id,
            summary=self.adjudication.summary,
            options=self.options,
        )


class CheckRun(ContractModel):
    check_id: str = Field(min_length=1)
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    action_request_id: str = Field(min_length=1)
    selected_candidate_id: str = Field(min_length=1)
    selected_skill_id: str = Field(min_length=1)
    difficulty: Literal["regular", "hard", "extreme"]
    target_value: int = Field(ge=0, le=100)
    status: Literal["awaiting_post_roll_decision", "resolved"]
    version: int = Field(default=1, ge=1)
    roll_count: int = Field(ge=1, le=2)
    roll: CheckRoll
    post_roll_options: tuple[PostRollOption, ...] = ()
    final_result: CheckRoll | None = None
    adjudication: ActionAdjudication


WorkflowRequest = SubmitAdjudicationRequest | CheckDecisionRequest | PostRollDecisionRequest


class CompletedAdjudicationCommand(ContractModel):
    request_id: str = Field(min_length=1)
    request: WorkflowRequest
    execution: AdjudicationExecution


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
