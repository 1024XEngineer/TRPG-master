"""Authoring-time ModuleContent v3 contract (issues #212 / #226 / #240 / #245).

This is item 1 of the implementation split in #212 §13: the public v3 contract and
its JSON Schema. It defines **what a module author writes**, nothing else — the
runtime counterparts (RuleAgenda, WorldTimeState, KnowledgeResolution, EndingDraft,
DomainEventV3, ActorLocationState …) belong to later items and are deliberately
absent here.

Why a new module instead of extending `contracts/module.py`: #226 freezes the
migration as *Breaking*, with Checkpoint / `module_rules` / `event_rules` losing
their runtime compatibility layer. v2 `ModuleContent` therefore has to survive
untouched — not as a runtime format, but as the **migration input** every v3
module is compiled from.

Domain nodes and their owners:

* `Information` / `Entity` / `Location` are Canon world nodes (#212 §3.1).
* `Rule` is a deterministic trigger declaration, never a natural-language
  matcher: an `agent_match` rule hands the Agent an opaque candidate menu, an
  `event` rule matches committed domain events (#226 §1–§2).
* Time is authored as `ModuleTimePolicySpec` only; the world clock itself is
  runtime state (#245).

Two root fields — `initial_state` and `world_profile` — are named in #212 §3.1
but never given a field design in any of the four issues. They are modelled here
with the minimum the rest of the contract actually references, and marked
provisional in their own docstrings so a later issue can extend them without
having to undo guesses.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, JsonValue, model_validator

from .adjudication import ActionEffect, CheckDegree
from .common import ContractModel
from .inventory import ItemComponent
from .module import ModulePresentation

# --------------------------------------------------------------------------- #
# shared vocabularies
# --------------------------------------------------------------------------- #

IDENTIFIER_PATTERN = r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$"

Identifier: TypeAlias = Annotated[
    str,
    Field(min_length=1, max_length=100, pattern=IDENTIFIER_PATTERN),
]

TargetKind: TypeAlias = Literal["information", "entity", "location", "actor", "world"]


def _require_unique_ids(items: tuple[object, ...], label: str) -> None:
    ids = [getattr(item, "id") for item in items]  # noqa: B009
    if len(ids) != len(set(ids)):
        raise ValueError(f"{label} id 必须唯一")


# --------------------------------------------------------------------------- #
# information (#212 §4.2)
# --------------------------------------------------------------------------- #


class InformationDiscoverySpec(ContractModel):
    """Whether the fact starts hidden, and who shares it once discovered."""

    initial: Literal["hidden", "known"] = "hidden"
    scope: Literal["party", "actor"] = "party"


class InformationAudienceSpec(ContractModel):
    keeper: bool = True
    player_when_discovered: bool = True


class InformationPresentationSpec(ContractModel):
    channels: tuple[Literal["narration", "journal", "handout"], ...] = ("narration",)
    show_in_ui: bool = True


class InformationRecoverySpec(ContractModel):
    """How hard the module insists on *this* route to the fact.

    `strict` must honour the declared sources; `adaptive` / `guaranteed` let the
    Agent reach the same Canon Information through a reasonable Runtime source —
    a neighbour, a public record, a clerk who looks it up — without ever letting
    it invent a fact that is not already Canon (#212 §4.2, §4.3).
    """

    policy: Literal["strict", "adaptive", "guaranteed"] = "adaptive"
    allowed_source_types: tuple[
        Literal[
            "explicit_entity",
            "explicit_location",
            "runtime_entity",
            "public_record",
            "environmental_source",
        ],
        ...,
    ] = ()

    @model_validator(mode="after")
    def validate_sources(self) -> InformationRecoverySpec:
        if self.policy == "strict" and not self.allowed_source_types:
            raise ValueError("strict Information 必须声明 allowed_source_types")
        if len(self.allowed_source_types) != len(set(self.allowed_source_types)):
            raise ValueError("allowed_source_types 必须唯一")
        return self


class InformationSpecV3(ContractModel):
    """One Canon fact, separated from every carrier that can deliver it."""

    id: Identifier
    kind: Literal["clue", "fact", "rumor", "testimony", "record"] = "clue"
    title: str = Field(min_length=1, max_length=200)
    # Keeper-only text. Never projected into PlayerView; the Agent sees it only
    # through the controlled Keeper capability view.
    keeper_content: str = Field(min_length=1)
    # What the player is allowed to read once the fact is released.
    player_content: str = Field(min_length=1)
    discovery: InformationDiscoverySpec = Field(
        default_factory=InformationDiscoverySpec
    )
    audience: InformationAudienceSpec = Field(default_factory=InformationAudienceSpec)
    presentation: InformationPresentationSpec = Field(
        default_factory=InformationPresentationSpec
    )
    criticality: Literal["essential", "supporting", "flavor"] = "supporting"
    recovery: InformationRecoverySpec = Field(default_factory=InformationRecoverySpec)


class KnowledgeGoalSpec(ContractModel):
    """What the party must end up *knowing*, independent of how they learn it."""

    id: Identifier
    target_information_ids: tuple[Identifier, ...] = Field(min_length=1)
    completion: Literal["all", "any"] = "all"
    required_for_core_resolution: bool = False

    @model_validator(mode="after")
    def validate_targets(self) -> KnowledgeGoalSpec:
        if len(self.target_information_ids) != len(set(self.target_information_ids)):
            raise ValueError("target_information_ids 必须唯一")
        return self


# --------------------------------------------------------------------------- #
# entities (#212 §8.2)
# --------------------------------------------------------------------------- #

EntityRelationKind: TypeAlias = Literal[
    "contains",
    "located_in",
    "owns",
    "carried_by",
    "knows",
    "guards",
    "attached_to",
    "related_to",
]


class EntityRelationSpec(ContractModel):
    """A semantic relation only.

    `owns` / `carried_by` / `contains` deliberately do not imply custody: an
    item's authoritative position is `ItemCustody` runtime state, and capacity,
    equipment slots and stacking are explicitly not frozen yet (#212 §8.2).
    """

    kind: EntityRelationKind
    target_id: Identifier


class EntitySpecV3(ContractModel):
    """A Canon NPC or object.

    Runtime entities the Agent proposes mid-session are not authored here; they
    carry `origin="runtime"` and live in GameState, and may never shadow a Canon
    id (#212 §8.2).
    """

    id: Identifier
    kind: Literal["npc", "object"]
    origin: Literal["canon"] = "canon"
    name: str = Field(min_length=1, max_length=200)
    player_visible_name: str = ""
    player_visible_aliases: tuple[str, ...] = ()
    description: str = ""
    located_in: Identifier | None = None
    relations: tuple[EntityRelationSpec, ...] = ()
    state: dict[str, JsonValue] = Field(default_factory=dict)
    item_component: ItemComponent | None = None
    visibility: Literal["public", "party", "actor", "keeper"] = "public"
    # Audience and discovery are separate concerns. A public entity may still
    # stay out of every player projection until registered, deterministic
    # predicates say it has been discovered.
    visibility_conditions: tuple[ConditionExpr, ...] = ()
    plot_relevance: bool = True
    lifecycle: Literal["campaign", "session"] = "campaign"


# --------------------------------------------------------------------------- #
# locations (#212 §7.3)
# --------------------------------------------------------------------------- #


class LocationSpecV3(ContractModel):
    """A place.

    `parent_location_id` drives the UI breadcrumb; reachability is a separate
    graph (`LocationEdgeSpec`). Conflating the two is what made v2 Scene exits
    unable to express "standing at the locked study door" (#212 §7.3, §7.4).
    """

    id: Identifier
    kind: Literal["region", "site", "room", "connector"]
    origin: Literal["canon", "system_seeded"] = "canon"
    name: str = Field(min_length=1, max_length=200)
    player_visible_name: str = ""
    player_visible_description: str = ""
    parent_location_id: Identifier | None = None
    region_id: Identifier | None = None
    relations: tuple[EntityRelationSpec, ...] = ()
    plot_relevance: bool = True
    lifecycle: Literal["campaign", "session", "room"] = "campaign"

    @model_validator(mode="after")
    def validate_hierarchy(self) -> LocationSpecV3:
        if self.parent_location_id == self.id:
            raise ValueError("Location 不能以自己为父地点")
        return self


class TravelCostSpec(ContractModel):
    minutes: int = Field(default=0, ge=0, le=10080)


class LocationEdgeSpec(ContractModel):
    """One directed route in the navigation graph.

    `access_point_id` is the Entity that gates the edge (a door, a gate). When it
    is set and locked, travel stops at that boundary instead of failing — that is
    what lets the player be "at the study door" rather than either inside or
    nowhere.
    """

    id: Identifier
    from_location_id: Identifier
    to_location_id: Identifier
    kind: Literal["public_network", "private", "concealed", "vertical"] = (
        "public_network"
    )
    traversal: Literal["automatic", "gated", "guided"] = "automatic"
    visibility: Literal["public", "party", "actor", "hidden"] = "public"
    access_point_id: Identifier | None = None
    conditions: tuple[ConditionExpr, ...] = ()
    travel_cost: TravelCostSpec = Field(default_factory=TravelCostSpec)
    origin: Literal["authored", "synthesized"] = "authored"

    @model_validator(mode="after")
    def validate_endpoints(self) -> LocationEdgeSpec:
        if self.from_location_id == self.to_location_id:
            raise ValueError("Location edge 的两端不能相同")
        return self


# --------------------------------------------------------------------------- #
# rule conditions (#226 §2)
# --------------------------------------------------------------------------- #


class AllCondition(ContractModel):
    op: Literal["all"] = "all"
    items: tuple[ConditionExpr, ...] = Field(min_length=1)


class AnyCondition(ContractModel):
    op: Literal["any"] = "any"
    items: tuple[ConditionExpr, ...] = Field(min_length=1)


class NotCondition(ContractModel):
    op: Literal["not"] = "not"
    item: ConditionExpr


class PredicateCondition(ContractModel):
    """A registered predicate, never a script.

    #226 §1 forbids scripts, database paths and arbitrary event payloads in
    rules; the predicate name must resolve to something the Engine registered.
    """

    op: Literal["predicate"] = "predicate"
    predicate: str = Field(min_length=1, max_length=100, pattern=IDENTIFIER_PATTERN)
    args: dict[str, JsonValue] = Field(default_factory=dict)


ConditionExpr: TypeAlias = Annotated[
    AllCondition | AnyCondition | NotCondition | PredicateCondition,
    Field(discriminator="op"),
]


# --------------------------------------------------------------------------- #
# rule triggers (#226 §2, #240 §5)
# --------------------------------------------------------------------------- #


class CandidateScopeSpec(ContractModel):
    """Which situations may surface this rule as an Agent candidate.

    #226 writes this as `scene_ids`; #240 §5 rules that a scene is a narrative
    chapter and is no longer the authoritative actor position, so v3 scopes by
    `location_ids` instead — the same reconciliation that moved
    `RuleMatchContextRefs` onto `actor_location_id` / `target_location_id`.
    """

    action_families: tuple[str, ...] = ()
    location_ids: tuple[Identifier, ...] = ()
    target_kinds: tuple[TargetKind, ...] = ()
    target_ids: tuple[Identifier, ...] = ()


class MatchQuestionSpec(ContractModel):
    kind: Literal["action_declaration", "method", "intent_relation"]
    semantic_hints: tuple[str, ...] = Field(min_length=1)


class MatchOptionAuthorSpec(ContractModel):
    """One opaque choice offered to the Agent.

    The Agent submits `id` and nothing else; the mapping from option to
    consequence exists only server-side, so a compromised or creative model
    cannot pick an outcome (#226 §1 设计结论).
    """

    id: Identifier
    semantic_hints: tuple[str, ...] = Field(min_length=1)


class BindingSlotSpec(ContractModel):
    name: str = Field(min_length=1, max_length=100, pattern=IDENTIFIER_PATTERN)
    source: Literal["actor", "target", "scene", "location"]
    required: bool = True


class AgentMatchTriggerSpec(ContractModel):
    kind: Literal["agent_match"] = "agent_match"
    required: bool = True
    decision_mode: Literal["selective", "exhaustive_for_scope"] = "selective"
    scope: CandidateScopeSpec = Field(default_factory=CandidateScopeSpec)
    question: MatchQuestionSpec
    options: tuple[MatchOptionAuthorSpec, ...] = Field(min_length=1)
    bindings: tuple[BindingSlotSpec, ...] = ()

    @model_validator(mode="after")
    def validate_options(self) -> AgentMatchTriggerSpec:
        _require_unique_ids(self.options, "Rule match option")
        names = [binding.name for binding in self.bindings]
        if len(names) != len(set(names)):
            raise ValueError("Rule binding name 必须唯一")
        return self


class EventTriggerSpec(ContractModel):
    """Matches a committed domain event, never the player's words (#212 §3.3)."""

    kind: Literal["event"] = "event"
    event_type: str = Field(min_length=1, max_length=100)
    when: ConditionExpr | None = None
    entry_branch_id: Identifier = "default"


RuleTriggerSpec: TypeAlias = Annotated[
    AgentMatchTriggerSpec | EventTriggerSpec,
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- #
# rule execution steps (#226 §4, §5)
# --------------------------------------------------------------------------- #


class RuleCheckSpec(ContractModel):
    """A check owned by the rule rather than proposed by the Agent.

    `parameters` may only carry fields the named Check Profile registered — the
    rule cannot restate the system's dice algebra (#226 §5).
    """

    profile_id: str = Field(min_length=1, max_length=100)
    actor_binding: str = Field(min_length=1, max_length=100)
    initiation_kind: Literal["active_action", "passive_rule"]
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    difficulty: Literal["regular", "hard", "extreme"] | None = None
    allow_luck: bool | None = None
    allow_push: bool | None = None


class EffectStep(ContractModel):
    id: Identifier
    kind: Literal["effect"] = "effect"
    effect: ActionEffect
    next_step_id: Identifier


class CheckStep(ContractModel):
    id: Identifier
    kind: Literal["check"] = "check"
    check: RuleCheckSpec
    result_routes: dict[CheckDegree, Identifier] = Field(min_length=1)


class AdjudicatedCheckStep(ContractModel):
    """Take over the check the Agent already proposed for this action.

    `effect_authority="rule"` is the point: the player picked the skill, but the
    published rule — not the Agent — owns what the result does.
    """

    id: Identifier
    kind: Literal["adjudicated_check"] = "adjudicated_check"
    adjudication_ref: Literal["current"] = "current"
    effect_authority: Literal["rule"] = "rule"
    result_routes: dict[CheckDegree, Identifier] = Field(min_length=1)
    cancel_step_id: Identifier


class InvokeRulesetActionStep(ContractModel):
    id: Identifier
    kind: Literal["invoke_ruleset_action"] = "invoke_ruleset_action"
    action_id: str = Field(min_length=1, max_length=100)
    actor_binding: str = Field(min_length=1, max_length=100)
    parameters: dict[str, JsonValue] = Field(default_factory=dict)
    next_step_id: Identifier


class CreateNpcActionOpportunityStep(ContractModel):
    """Positive authorisation for an NPC to act; nothing acts implicitly."""

    id: Identifier
    kind: Literal["create_npc_action_opportunity"] = "create_npc_action_opportunity"
    entity_id: Identifier
    action_id: str = Field(min_length=1, max_length=100)
    next_step_id: Identifier


class CreateTimeTaskStep(ContractModel):
    """Schema owned by #245; referenced here so a rule can schedule one."""

    id: Identifier
    kind: Literal["create_time_task"] = "create_time_task"
    task_id: Identifier
    next_step_id: Identifier


class CancelTimeTaskStep(ContractModel):
    id: Identifier
    kind: Literal["cancel_time_task"] = "cancel_time_task"
    task_id: Identifier
    next_step_id: Identifier


class PresentationStep(ContractModel):
    """Hand the Narrator a reference, not prose to copy."""

    id: Identifier
    kind: Literal["presentation"] = "presentation"
    presentation_id: Identifier
    next_step_id: Identifier


class AwaitPlayerInputStep(ContractModel):
    """Suspend the agenda until the player speaks again (#226 §4)."""

    id: Identifier
    kind: Literal["await_player_input"] = "await_player_input"
    resume_step_id: Identifier


class FinishStep(ContractModel):
    id: Identifier
    kind: Literal["finish"] = "finish"


RuleStepSpec: TypeAlias = Annotated[
    EffectStep
    | CheckStep
    | AdjudicatedCheckStep
    | InvokeRulesetActionStep
    | CreateNpcActionOpportunityStep
    | CreateTimeTaskStep
    | CancelTimeTaskStep
    | PresentationStep
    | AwaitPlayerInputStep
    | FinishStep,
    Field(discriminator="kind"),
]


class ExecutionBranchSpec(ContractModel):
    id: Identifier
    entry_step_id: Identifier


class RuleExecutionSpec(ContractModel):
    branches: tuple[ExecutionBranchSpec, ...] = Field(min_length=1)
    steps: tuple[RuleStepSpec, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_graph(self) -> RuleExecutionSpec:
        _require_unique_ids(self.branches, "Rule execution branch")
        _require_unique_ids(self.steps, "Rule execution step")
        step_ids = {step.id for step in self.steps}
        for branch in self.branches:
            if branch.entry_step_id not in step_ids:
                raise ValueError(
                    f"分支 {branch.id} 的入口步骤不存在: {branch.entry_step_id}"
                )
        for step in self.steps:
            for target in _step_targets(step):
                if target not in step_ids:
                    raise ValueError(f"步骤 {step.id} 指向不存在的步骤: {target}")
        return self


def _step_targets(step: RuleStepSpec) -> tuple[str, ...]:
    """Every step id this step can hand control to."""

    if isinstance(step, CheckStep | AdjudicatedCheckStep):
        routes = tuple(step.result_routes.values())
        if isinstance(step, AdjudicatedCheckStep):
            return (*routes, step.cancel_step_id)
        return routes
    if isinstance(step, AwaitPlayerInputStep):
        return (step.resume_step_id,)
    if isinstance(step, FinishStep):
        return ()
    return (step.next_step_id,)


class RulePresentationSpec(ContractModel):
    id: Identifier
    player_safe_summary: str = Field(default="", max_length=500)
    narration_constraints: tuple[str, ...] = ()


class RuleLimitsSpec(ContractModel):
    max_chain_depth: int = Field(default=16, ge=1, le=64)
    max_steps: int = Field(default=128, ge=1, le=1024)


class RuleSpecV3(ContractModel):
    """One authored rule.

    Its immutable identity is `(module_id, module_version, rule_id)`; a running
    session pins a ModuleVersion so a republished rule can never change the
    meaning of an agenda already in flight (#226 §1).
    """

    id: Identifier
    priority: int = Field(default=0, ge=-1000, le=1000)
    trigger: RuleTriggerSpec
    execution: RuleExecutionSpec
    presentation: RulePresentationSpec | None = None
    limits: RuleLimitsSpec = Field(default_factory=RuleLimitsSpec)

    @model_validator(mode="after")
    def validate_entry_branch(self) -> RuleSpecV3:
        branch_ids = {branch.id for branch in self.execution.branches}
        if isinstance(self.trigger, EventTriggerSpec):
            if self.trigger.entry_branch_id not in branch_ids:
                raise ValueError(
                    f"event rule {self.id} 的 entry_branch_id 不存在: "
                    f"{self.trigger.entry_branch_id}"
                )
        else:
            # An agent_match rule routes by option id: every option the Agent can
            # pick must land on a declared branch, or picking it would dead-end.
            missing = [
                option.id
                for option in self.trigger.options
                if option.id not in branch_ids
            ]
            if missing:
                raise ValueError(
                    f"agent_match rule {self.id} 的候选没有对应分支: {', '.join(missing)}"
                )
        return self


# --------------------------------------------------------------------------- #
# resolution and endings (#212 §10.2)
# --------------------------------------------------------------------------- #


class CoreResolutionSpec(ContractModel):
    required_goal_ids: tuple[Identifier, ...] = ()
    completion: Literal["all", "any"] = "all"


class EndingPolicySpec(ContractModel):
    """Reaching the core resolution opens the ending; it does not force it.

    `allow_continue_after_core_resolution` is the fix for v2's habit of ending
    the session the moment the main thread closed (#212 §1).
    """

    allow_continue_after_core_resolution: bool = True
    require_no_pending_action: bool = True
    allow_grounded_variations: bool = True
    facets: tuple[str, ...] = ()


class EndingAnchorSpec(ContractModel):
    id: Identifier
    tone: str = Field(default="", max_length=100)
    required_fact_refs: tuple[Identifier, ...] = ()
    forbidden_claims: tuple[str, ...] = ()


# --------------------------------------------------------------------------- #
# time policy (#245 §二.1)
# --------------------------------------------------------------------------- #


class TimePointSpec(ContractModel):
    id: Identifier
    hour_of_day: int = Field(ge=0, le=23)
    order: int = Field(ge=0)


DEFAULT_TIME_POINTS: tuple[TimePointSpec, ...] = (
    TimePointSpec(id="hour_00", hour_of_day=0, order=0),
    TimePointSpec(id="hour_06", hour_of_day=6, order=1),
    TimePointSpec(id="hour_12", hour_of_day=12, order=2),
    TimePointSpec(id="hour_18", hour_of_day=18, order=3),
)


class ModuleTimePolicySpec(ContractModel):
    """Discrete time points; the clock jumps between them, it does not tick."""

    default_points: tuple[TimePointSpec, ...] = DEFAULT_TIME_POINTS
    storage_precision: Literal["hour"] = "hour"
    progression: Literal["host_controlled_discrete"] = "host_controlled_discrete"
    actions_per_point: Literal["multiple"] = "multiple"

    @model_validator(mode="after")
    def validate_points(self) -> ModuleTimePolicySpec:
        if not self.default_points:
            raise ValueError("TimePolicy 至少需要一个时间点")
        _require_unique_ids(self.default_points, "TimePoint")
        orders = [point.order for point in self.default_points]
        if sorted(orders) != list(range(len(orders))):
            raise ValueError("TimePoint order 必须是从 0 开始的连续序列")
        by_order = sorted(self.default_points, key=lambda point: point.order)
        hours = [point.hour_of_day for point in by_order]
        if hours != sorted(hours) or len(hours) != len(set(hours)):
            raise ValueError("TimePoint hour_of_day 必须随 order 严格递增")
        return self


# --------------------------------------------------------------------------- #
# provisional roots (#212 §3.1 names them; no issue gives a field design)
# --------------------------------------------------------------------------- #


class WorldProfileSpec(ContractModel):
    """Setting constraints the Agent must respect when proposing Runtime content.

    Provisional: #212 §7.5 only requires that an Agent-proposed inn "符合
    world_profile". Modelled with the minimum needed to judge that, so a later
    issue can extend it without unwinding invented structure.
    """

    era: str = Field(default="", max_length=100)
    region: str = Field(default="", max_length=100)
    technology_level: str = Field(default="", max_length=100)
    tone: str = Field(default="", max_length=200)
    forbidden_content: tuple[str, ...] = ()


class ActorPlacementSpec(ContractModel):
    """Where investigators start. Actor position is runtime state (#240 §1)."""

    location_id: Identifier


class InitialStateSpec(ContractModel):
    """The opening world snapshot.

    Provisional, same reason as `WorldProfileSpec`: only the fields the rest of
    this contract references are modelled.
    """

    start_location_id: Identifier
    default_actor_placement: ActorPlacementSpec | None = None
    revealed_information_ids: tuple[Identifier, ...] = ()
    start_time_point_id: Identifier | None = None
    entity_state: dict[Identifier, dict[str, JsonValue]] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# root
# --------------------------------------------------------------------------- #


class ModuleContentV3(ContractModel):
    """The v3 module file (#212 §3.1).

    Structural invariants only live here; cross-collection reference checks
    (does this goal name a real Information? does this edge name a real
    Location?) belong to the semantic validator, which can report every problem
    at once instead of aborting on the first.
    """

    content_schema_version: Literal[3] = 3
    module_id: Identifier
    version: str = Field(min_length=1, max_length=50)
    world_ref: str = Field(min_length=1, max_length=100)
    background: str = Field(min_length=1)

    information: tuple[InformationSpecV3, ...] = ()
    knowledge_goals: tuple[KnowledgeGoalSpec, ...] = ()
    entities: tuple[EntitySpecV3, ...] = ()
    locations: tuple[LocationSpecV3, ...] = Field(min_length=1)
    location_edges: tuple[LocationEdgeSpec, ...] = ()
    rules: tuple[RuleSpecV3, ...] = ()

    core_resolution: CoreResolutionSpec = Field(default_factory=CoreResolutionSpec)
    ending_policy: EndingPolicySpec = Field(default_factory=EndingPolicySpec)
    ending_anchors: tuple[EndingAnchorSpec, ...] = ()

    presentation: ModulePresentation
    initial_state: InitialStateSpec
    world_profile: WorldProfileSpec = Field(default_factory=WorldProfileSpec)
    time_policy: ModuleTimePolicySpec = Field(default_factory=ModuleTimePolicySpec)

    @model_validator(mode="after")
    def validate_unique_ids(self) -> ModuleContentV3:
        _require_unique_ids(self.information, "Information")
        _require_unique_ids(self.knowledge_goals, "KnowledgeGoal")
        _require_unique_ids(self.entities, "Entity")
        _require_unique_ids(self.locations, "Location")
        _require_unique_ids(self.location_edges, "Location edge")
        _require_unique_ids(self.rules, "Rule")
        _require_unique_ids(self.ending_anchors, "Ending anchor")
        return self


__all__ = [
    "DEFAULT_TIME_POINTS",
    "IDENTIFIER_PATTERN",
    "ActorPlacementSpec",
    "AdjudicatedCheckStep",
    "AgentMatchTriggerSpec",
    "AllCondition",
    "AnyCondition",
    "AwaitPlayerInputStep",
    "BindingSlotSpec",
    "CancelTimeTaskStep",
    "CandidateScopeSpec",
    "CheckStep",
    "ConditionExpr",
    "CoreResolutionSpec",
    "CreateNpcActionOpportunityStep",
    "CreateTimeTaskStep",
    "EffectStep",
    "EndingAnchorSpec",
    "EndingPolicySpec",
    "EntityRelationKind",
    "EntityRelationSpec",
    "EntitySpecV3",
    "EventTriggerSpec",
    "ExecutionBranchSpec",
    "FinishStep",
    "Identifier",
    "InformationAudienceSpec",
    "InformationDiscoverySpec",
    "InformationPresentationSpec",
    "InformationRecoverySpec",
    "InformationSpecV3",
    "InitialStateSpec",
    "InvokeRulesetActionStep",
    "KnowledgeGoalSpec",
    "LocationEdgeSpec",
    "LocationSpecV3",
    "MatchOptionAuthorSpec",
    "MatchQuestionSpec",
    "ModuleContentV3",
    "ModuleTimePolicySpec",
    "NotCondition",
    "PredicateCondition",
    "PresentationStep",
    "RuleCheckSpec",
    "RuleExecutionSpec",
    "RuleLimitsSpec",
    "RulePresentationSpec",
    "RuleSpecV3",
    "RuleStepSpec",
    "RuleTriggerSpec",
    "TargetKind",
    "TimePointSpec",
    "TravelCostSpec",
    "WorldProfileSpec",
]
