"""Member-B internal state, Event, and execution-result models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, JsonValue

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionRequest,
    ActionResult,
    AdjudicationExecution,
    AuthorityLevel,
    CheckDecisionRequest,
    ClassificationCoverage,
    ContractModel,
    EndingResolution,
    ItemInstance,
    ItemKnowledge,
    LocationKnowledge,
    ModuleContentV3,
    PendingCheckDecisionView,
    PendingCheckOption,
    PostRollDecisionRequest,
    PostRollOption,
    SubmitAdjudicationRequest,
    TravelInterrupted,
    ValidationResult,
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


DAY_STARTS_HOUR = 6
NIGHT_STARTS_HOUR = 18


def time_of_day_at_hour(hour_of_day: int) -> Literal["day", "night"]:
    """The single day/night boundary: 06:00–18:00 is day.

    Derived, never stored. Two places used to compute this independently and gave
    different answers; they only agreed because the v2 fixture opened at midnight
    (#226).
    """

    return "day" if DAY_STARTS_HOUR <= hour_of_day < NIGHT_STARTS_HOUR else "night"


class WorldTimePoint(ContractModel):
    """An exact hour on the world calendar (#245 §二.2)."""

    day_index: int = Field(default=0, ge=0)
    hour_of_day: int = Field(default=0, ge=0, le=23)

    @property
    def absolute_hour(self) -> int:
        """Total ordering across days, so "next point" is a plain comparison."""

        return self.day_index * 24 + self.hour_of_day

    @property
    def time_of_day(self) -> Literal["day", "night"]:
        return time_of_day_at_hour(self.hour_of_day)


class WorldTimeState(ContractModel):
    """Where the room currently sits on the discrete timeline (#245 §一.1).

    Time never flows: it does not tick with real time, does not accrue per action,
    and cannot land between authored points. It only jumps from `current_point_id`
    to the next point in the ordered timeline.

    #245 §二.2 also lists room_id / module_id / module_version / revision /
    last_event_id on this record. Those are deliberately not duplicated here —
    EngineRuntimeSnapshot already carries them, and a second copy of `revision`
    inside the committed state is exactly the kind of thing that silently drifts.
    The read-side view assembles the full shape from both (S2).
    """

    # 默认落在正午而不是午夜：v2 房间没有 time_policy，起点是任选的，而
    # time_of_day 现在是推导出来的——午夜会让"没声明时间的房间一开局就是夜里"。
    # v3 房间一律由 initial_state.start_time_point_id 覆盖这个默认值。
    current: WorldTimePoint = Field(
        default_factory=lambda: WorldTimePoint(day_index=0, hour_of_day=12)
    )
    current_point_id: str = Field(default="hour_12", min_length=1)

    @property
    def time_of_day(self) -> Literal["day", "night"]:
        return self.current.time_of_day


class AgendaSource(ContractModel):
    """The committed fact that created a durable RuleAgenda (#226 §4)."""

    kind: Literal["action", "event"]
    id: str = Field(min_length=1)


class AgendaItem(ContractModel):
    """One Event Rule invocation in its deterministic queue position."""

    source_event_id: str = Field(min_length=1)
    event_sequence: int = Field(ge=1)
    rule_id: str = Field(min_length=1)
    rule_priority: int
    branch_id: str = Field(min_length=1)
    status: Literal["queued", "running", "completed", "skipped", "failed"] = "queued"


class RuleAgenda(ContractModel):
    """Persisted Rule cursor, queue, budgets, and worker lease (#226 §4).

    Lease changes are coordination state rather than gameplay facts. Stores use
    ``lease_version`` as a compare-and-swap token without changing the room's
    Event revision.
    """

    agenda_id: str = Field(min_length=1)
    room_id: str = Field(min_length=1)
    module_id: str = Field(min_length=1)
    module_version: str = Field(min_length=1)
    correlation_id: str = Field(min_length=1)
    root_source: AgendaSource
    status: Literal[
        "running",
        "awaiting_active_check",
        "awaiting_passive_check",
        "awaiting_presentation",
        "awaiting_player_input",
        "stable",
        "failed",
    ] = "running"
    source_event_ids: tuple[str, ...] = ()
    queue: tuple[AgendaItem, ...] = ()
    current_rule_id: str | None = None
    current_branch_id: str | None = None
    current_step_id: str | None = None
    pending_check_id: str | None = None
    pending_boundary_id: str | None = None
    pending_rule_input_id: str | None = None
    revision: str = Field(min_length=1)
    chain_depth: int = Field(default=0, ge=0)
    step_count: int = Field(default=0, ge=0)
    max_chain_depth: int = Field(default=16, ge=1, le=64)
    max_steps: int = Field(default=128, ge=1, le=1024)
    failure_code: str | None = None
    lease_owner: str | None = None
    lease_expires_at: datetime | None = None
    lease_version: int = Field(default=0, ge=0)


class GameState(ContractModel):
    """Authoritative room state loaded and committed only through EngineStore."""

    room_id: str
    scene_id: str
    phase: Literal["playing", "ended"] = "playing"
    ending_id: str | None = None
    event_sequence: int = Field(default=0, ge=0)
    actors: dict[str, ActorState]
    entities: dict[str, dict[str, JsonValue]]
    # 仅记录由公开标准状态效果产生的键；值仍保存在现有实体状态 JSON 中。
    public_entity_state_keys: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    world_time: WorldTimeState = Field(default_factory=WorldTimeState)
    discovered_facts: tuple[str, ...] = ()
    actor_discovered_facts: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    runtime_locations: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    runtime_entities: dict[str, dict[str, JsonValue]] = Field(default_factory=dict)
    visibility_overrides: dict[str, bool] = Field(default_factory=dict)
    party_location_knowledge: dict[str, LocationKnowledge] = Field(default_factory=dict)
    actor_location_knowledge: dict[str, dict[str, LocationKnowledge]] = Field(default_factory=dict)
    actor_position_contexts: dict[str, TravelInterrupted] = Field(default_factory=dict)
    item_instances: dict[str, ItemInstance] = Field(default_factory=dict)
    party_item_knowledge: dict[str, ItemKnowledge] = Field(default_factory=dict)
    actor_item_knowledge: dict[str, dict[str, ItemKnowledge]] = Field(default_factory=dict)
    rule_agendas: dict[str, RuleAgenda] = Field(default_factory=dict)
    core_resolved: bool = False
    ending_available: bool = False
    ending_resolution: EndingResolution | None = None


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
    # 玩家选技能时菜单上显示的那个名字。留住它，结果消息才和当时看到的一致；
    # 调用方拿 skill_id 反查 ruleset 会在自定义技能上对不上。
    selected_skill_name: str = Field(min_length=1)
    difficulty: Literal["regular", "hard", "extreme"]
    target_value: int = Field(ge=0, le=100)
    status: Literal["awaiting_post_roll_decision", "resolved"]
    version: int = Field(default=1, ge=1)
    roll_count: int = Field(ge=1, le=2)
    roll: CheckRoll
    post_roll_options: tuple[PostRollOption, ...] = ()
    final_result: CheckRoll | None = None
    resolution_kind: Literal["initial_roll", "accept_result", "spend_luck", "push"] = "initial_roll"
    luck_spent: int | None = Field(default=None, ge=1)
    adjudication: ActionAdjudication


WorkflowRequest = SubmitAdjudicationRequest | CheckDecisionRequest | PostRollDecisionRequest


class CompletedAdjudicationCommand(ContractModel):
    request_id: str = Field(min_length=1)
    request: WorkflowRequest
    execution: AdjudicationExecution
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    validation: ValidationResult | None = None
    committed_authority_level: AuthorityLevel | None = None
    classification_coverage: ClassificationCoverage = "complete"


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
    module_content: ModuleContentV3
    game_state: GameState
    revision: str = Field(min_length=1)

    @property
    def canon_information_ids(self) -> set[str]:
        return {item.id for item in self.module_content.information}

    @property
    def canon_entity_ids(self) -> set[str]:
        return {item.id for item in self.module_content.entities}

    @property
    def canon_location_ids(self) -> set[str]:
        return {item.id for item in self.module_content.locations}

    @property
    def canon_ending_ids(self) -> set[str]:
        return {item.id for item in self.module_content.ending_anchors}


class CompletedAction(ContractModel):
    """Original command and semantic result retained for idempotent replay."""

    request: ActionRequest
    execution: EngineExecutionResult
