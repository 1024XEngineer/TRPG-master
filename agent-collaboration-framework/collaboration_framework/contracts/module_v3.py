"""Authoring-time ModuleContent v3 contract (issues #212 / #226 / #240 / #245).

This is item 1 of the implementation split in #212 §13: the public v3 contract and
its JSON Schema. It defines **what a module author writes**, nothing else — the
runtime counterparts (RuleAgenda, WorldTimeState, KnowledgeResolution, EndingDraft,
DomainEventV3, ActorLocationState …) belong to later items and are deliberately
absent here.

This started as a separate module because #226 froze the migration as *Breaking*
and v2 `ModuleContent` still had to survive as the migration input. That input is
gone: every published module is v3, and the v1/v2 contract was deleted in #384.
What is left here is simply the one module content contract.

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

# --------------------------------------------------------------------------- #
# player-facing publication metadata
#
# 这两个类原本住在 v1 的 contracts/module.py 里，但它们描述的是「模组怎么呈现
# 给玩家」，与 schema 版本无关，v3 一直在用（`ModuleContentV3.presentation`）。
# v1 契约删除时它们必须留下，所以先搬到这里 (#384)。
# --------------------------------------------------------------------------- #


class ModuleStoryPage(ContractModel):
    """A player-safe page shown before character creation."""

    title: str = ""
    content: str = Field(min_length=1)


class ModulePresentation(ContractModel):
    """Player-facing publication metadata, separate from keeper context."""

    title: str = Field(min_length=1)
    name_en: str | None = None
    synopsis: str = Field(min_length=1)
    players_min: int = Field(ge=1)
    players_max: int = Field(ge=1)
    difficulty: int = Field(ge=1, le=3)
    estimated_duration: str = Field(min_length=1)
    story_label: str | None = None
    subtitle: str | None = None
    authors: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    player_intro_pages: tuple[ModuleStoryPage, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_player_range(self) -> ModulePresentation:
        if self.players_min > self.players_max:
            raise ValueError("players_min 不能大于 players_max")
        return self


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


class InitialCustodySpec(ContractModel):
    """声明实体在开局种子中的权威持有位置。"""

    kind: Literal["location", "starting_actor"]


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
    # 这是开局种子语义，不等同于普通的 EntityRelation。
    initial_custody: InitialCustodySpec | None = None
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
    # scope answers "what kind of action could match"; when answers whether
    # that authored opportunity exists in the current authoritative state.
    # Keeping the condition on the trigger lets publication and submission
    # evaluate the exact same expression instead of trusting a stale menu.
    # Omit the default from persisted ModuleVersion JSON. Adding this optional
    # field must not rewrite every existing agent_match as ``"when": null``;
    # immutable snapshots compare normalized JSON for same-version drift.
    when: ConditionExpr | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
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


class TimeTaskTargetSpec(ContractModel):
    """定时任务在哪一刻到期（#245 §5 / #415 §阶段四）。

    两种写法二选一：

    - `point_id` —— 绑到模组已经声明的默认点上。不必再写小时，它由
      `TimePointSpec` 唯一确定。
    - `day_index` + `hour_of_day` —— 剧情临时点，引擎会在两个默认点之间插入
      一次性 occurrence。

    两个都给或都不给都是错的：前者可能自相矛盾，后者根本没说到期时间。
    """

    point_id: Identifier | None = None
    day_index: int | None = Field(default=None, ge=0)
    hour_of_day: int | None = Field(default=None, ge=0, le=23)
    # 相对当前时刻还是绝对日历。默认点写法只能用绝对（点本身带着小时），
    # 临时点两种都行：「三小时后」是相对，「第二天凌晨两点」是绝对。
    relative: bool = False

    @model_validator(mode="after")
    def validate_target(self) -> TimeTaskTargetSpec:
        by_point = self.point_id is not None
        by_clock = self.hour_of_day is not None
        if by_point == by_clock:
            raise ValueError("TimeTaskTarget 必须二选一：point_id 或 hour_of_day")
        if by_point and (self.day_index is not None or self.relative):
            raise ValueError(
                "绑定默认点的 TimeTaskTarget 不能再声明 day_index 或 relative"
            )
        if self.relative and self.day_index is not None:
            # `relative` 说 hour_of_day 是偏移量，`day_index` 属于绝对日历那一
            # 套。两个一起给就是两种寻址模式并存，而契约没有、也不该有优先级
            # 规则——到期语义对调度器是歧义的，只能在发布期拒绝。
            raise ValueError("relative 的 TimeTaskTarget 不能再声明 day_index")
        if by_clock and not self.relative and self.day_index is None:
            raise ValueError("绝对时刻的 TimeTaskTarget 必须声明 day_index")
        return self


class TimeTaskSpec(ContractModel):
    """一次定时任务的作者态声明（#245 §5）。

    `task_key` 不是运行时 id：同一条规则可能为不同的绑定各排一个任务
    （「每个被跟踪的 NPC 三小时后现身」），运行时 id 由 key + bindings 生成。
    `cancel_time_task` 也是按 key + bindings 定位的，所以两边必须对得上。
    """

    task_key: Identifier
    target: TimeTaskTargetSpec
    # 同一刻到期的多个任务按 `priority` 再按 task_id 稳定排序，避免同点多任务
    # 的结算顺序随字典遍历漂移。
    priority: int = 0
    # `hidden` 的任务不向玩家暴露它插出来的那个临时点是什么时候、为什么。
    visibility: Literal["public", "hidden"] = "public"
    # 到期时从这条规则的哪个分支继续结算。
    on_due_branch_id: Identifier
    bindings: dict[str, JsonValue] = Field(default_factory=dict)


class CreateTimeTaskStep(ContractModel):
    """Schema owned by #245; referenced here so a rule can schedule one.

    以前这里只有一个 `task_id`，没有目标时间——也就是说这个 step **根本无法
    实际创建任务**，它在 registry 里被登记成 `step_kind_has_no_executor` 是
    诚实的。改成携带完整 `TimeTaskSpec`（#415 §阶段四）。
    """

    id: Identifier
    kind: Literal["create_time_task"] = "create_time_task"
    task: TimeTaskSpec
    next_step_id: Identifier


class CancelTimeTaskStep(ContractModel):
    """按 key + bindings 定位并取消，不按运行时 id。

    规则写的时候还不知道运行时 id 长什么样；它知道的是自己当初用哪个
    `task_key` 和哪组绑定排的任务。
    """

    id: Identifier
    kind: Literal["cancel_time_task"] = "cancel_time_task"
    task_key: Identifier
    bindings: dict[str, JsonValue] = Field(default_factory=dict)
    # 取消是有原因的（目标已死、玩家先一步阻止了它），原因要能进审计事件。
    reason_code: str = Field(min_length=1, max_length=64)
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
    # `presentation: RulePresentationSpec | None` 曾在这里。它从未有过任何读者，
    # #288 已结案为删除（#398 §范围「顺带清理」执行）。`PresentationStep` 本身
    # 保留但依旧不接通，所以它的 `presentation_id` 现在没有可解析的目标——两个
    # 已发布模组都没有声明过 presentation 或 presentation step。
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


# 三件事以前挤在 `time_of_day` 一个值上，这里把它们拆开（#415 §阶段一）：
#
# | 层       | 字段                 | 谁写                         | 谁读                        |
# |----------|----------------------|------------------------------|-----------------------------|
# | 精确身份 | `id` / `hour_of_day` | 模组                         | 引擎排序、`time_point_is`   |
# | 规则语义 | `time_segment`       | 模组逐点声明，缺省按小时推导 | 通用规则层 `time_of_day_is` |
# | 玩家措辞 | `label`              | 模组                         | 仅投影，规则不得读          |
#
# `label` 不能替代枚举：它是自由文本，通用规则若匹配「晚上」这个显示字符串，
# 模组改写成「深夜」就失效，等于把模组的表达习惯塞进通用契约——#401 §1 明令
# 禁止的方向。枚举也不能替代 `label`：通用 CoC7 规则（夜间侦查减值、只在夜里
# 出现的生物）必须对所有 CoC 7e 模组成立，它问得出「现在是不是夜里」，问不出
# 「现在是不是 `h02`」，后者是模组私有 id。
TimeSegment: TypeAlias = Literal["late_night", "morning", "afternoon", "evening"]

# `time_of_day_is` 的查询值空间。粗粒度别名**只在查询里存在**，不作为运行态
# 存储值：存 `night` 就再也分不出凌晨和晚上，而那正是本 Issue 要解决的问题。
TimeOfDayQuery: TypeAlias = Literal[
    "day", "night", "late_night", "morning", "afternoon", "evening"
]

DAY_SEGMENTS: frozenset[TimeSegment] = frozenset({"morning", "afternoon"})
NIGHT_SEGMENTS: frozenset[TimeSegment] = frozenset({"evening", "late_night"})

# 缺省推导表，写成上界序列而不是四个 if：新增段位只需要插一行，边界不会
# 在两个地方各写一遍。旧的 `time_of_day_at_hour` 硬编码 06–18，声明 05:00
# 表示「黎明」的模组会被判成 night，这就是它被替换掉的原因。
_SEGMENT_HOUR_BOUNDS: tuple[tuple[int, TimeSegment], ...] = (
    (6, "late_night"),
    (12, "morning"),
    (18, "afternoon"),
    (24, "evening"),
)

_DEFAULT_SEGMENT_LABELS: dict[TimeSegment, str] = {
    "late_night": "凌晨",
    "morning": "上午",
    "afternoon": "下午",
    "evening": "晚上",
}


def segment_at_hour(hour_of_day: int) -> TimeSegment:
    """00–05 late_night / 06–11 morning / 12–17 afternoon / 18–23 evening。

    两端都校验。这个函数从公共 contracts 导出，绕过 `TimePointSpec` 直接调用
    它的消费者不该把非法输入静默归类——只查上界的话 `-1` 会安静地变成凌晨。
    """

    if not 0 <= hour_of_day <= 23:
        raise ValueError(f"hour_of_day 必须落在 0–23: {hour_of_day}")
    for upper_bound, segment in _SEGMENT_HOUR_BOUNDS:
        if hour_of_day < upper_bound:
            return segment
    raise AssertionError("unreachable: 上面的区间已经覆盖 0–23")


def default_label_for(segment: TimeSegment) -> str:
    """没有声明 `label` 的时间点给玩家看什么。"""

    return _DEFAULT_SEGMENT_LABELS[segment]


def matches_time_query(segment: TimeSegment, query: object) -> bool:
    """四段值精确匹配，`day` / `night` 按别名集合匹配。

    追书人既有的 `time_of_day_is night` 因此不经迁移继续成立。
    """

    if query == "day":
        return segment in DAY_SEGMENTS
    if query == "night":
        return segment in NIGHT_SEGMENTS
    return segment == query


class TimePointSpec(ContractModel):
    id: Identifier
    hour_of_day: int = Field(ge=0, le=23)
    order: int = Field(ge=0)
    # 规则语义时段，缺省由 `hour_of_day` 推导，模组可逐点覆盖：05:00 声明成
    # `morning` 之后，通用的 `time_of_day_is day` 就在这一点成立。
    time_segment: TimeSegment | None = None
    # 玩家可见短措辞（「黎明」「深夜」）。**规则不得读取**，也不得把剧情正文
    # 塞进来——长度上限的作用就是让后者在发布期失败，而不是在玩家屏幕上。
    label: str | None = Field(default=None, min_length=1, max_length=20)

    @property
    def resolved_segment(self) -> TimeSegment:
        return self.time_segment or segment_at_hour(self.hour_of_day)

    @property
    def resolved_label(self) -> str:
        return self.label or default_label_for(self.resolved_segment)


DEFAULT_TIME_POINTS: tuple[TimePointSpec, ...] = (
    TimePointSpec(id="hour_00", hour_of_day=0, order=0),
    TimePointSpec(id="hour_06", hour_of_day=6, order=1),
    TimePointSpec(id="hour_12", hour_of_day=12, order=2),
    TimePointSpec(id="hour_18", hour_of_day=18, order=3),
)


class TerminalTimePointSpec(ContractModel):
    """时间线的最后一刻（#415 §阶段二）。

    终点必须标识时间点的某一次 **occurrence**，不能只给 point id：时间线是个
    环，`hour_18` 每天都会来一次，「第三天 18:00 结束」和「明天 18:00 结束」
    是两件事。`day_index` 与运行态一致，开局当天为 0，所以第三天 18:00 写作
    `{point_id: "hour_18", day_index: 2}`。

    不重复保存 `hour_of_day`：它由 `point_id` 对应的 `TimePointSpec` 唯一确定，
    两个字段互相矛盾比少一个字段更糟。
    """

    point_id: Identifier
    day_index: int = Field(ge=0)


class ModuleTimePolicySpec(ContractModel):
    """Discrete time points; the clock jumps between them, it does not tick.

    时间线是一个**按 `hour_of_day` 升序声明的环**。起点由
    `initial_state.start_time_point_id` 落在环上任意一点，越过末点时回卷并
    `day_index + 1`。跨午夜的夜晚因此今天就能表达，不需要按时序声明：

        按小时升序声明 00/02/18/20/22，起点指定 hour_18
          D0 18:00 → D0 20:00 → D0 22:00 → D1 00:00 → D1 02:00 → D1 18:00
                                            ^^^^^^ 越过末点回卷，day_index + 1

    下面 `validate_points` 的「`hour_of_day` 必须随 `order` 严格递增」是**声明
    顺序**约束，不是表达力约束——它保证 `order` 就是环上的位置，别的什么都不
    保证（#415 §一条需要先澄清的非缺口）。

    `default_points` 是**完整覆盖**，解析侧不得把模组自定义的点与默认四点机械
    合并：多合出来的点会制造额外推进边界，也会让同一条 night 规则在一天里命中
    两次（#415 §与解析侧的分界）。
    """

    default_points: tuple[TimePointSpec, ...] = DEFAULT_TIME_POINTS
    storage_precision: Literal["hour"] = "hour"
    progression: Literal["host_controlled_discrete"] = "host_controlled_discrete"
    actions_per_point: Literal["multiple"] = "multiple"
    # 没声明终点的模组维持现有环形回卷，既有模组不受影响。声明了终点的模组
    # 走到那一刻之后拒绝继续推进——单夜模组不再"一觉睡到第二天"。
    terminal_point: TerminalTimePointSpec | None = None

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
        if self.terminal_point is not None and not any(
            point.id == self.terminal_point.point_id for point in self.default_points
        ):
            raise ValueError(
                f"terminal_point 引用了不存在的时间点: {self.terminal_point.point_id}"
            )
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

    @model_validator(mode="after")
    def validate_terminal_point_is_reachable(self) -> ModuleContentV3:
        """终点必须落在从开局时刻出发的那条 walk 上（#415 §阶段二）。

        只能在根上校验：终点声明在 `time_policy` 里，开局时刻在 `initial_state`
        里，`ModuleTimePolicySpec` 自己看不到后者。

        环从起点开始走：起点及其之后的点当天到达，起点之前的点要等回卷之后的
        第二天。所以「第一天 00:00 结束」配上「18:00 开局」是不可达的——那一刻
        在开局之前，游戏会开在一条已经越过终点的时间线上。
        """

        terminal = self.time_policy.terminal_point
        if terminal is None:
            return self

        points = sorted(self.time_policy.default_points, key=lambda point: point.order)
        start_id = self.initial_state.start_time_point_id
        # 与 engine.initialization._world_time_for 同一条回退：声明的起点不在
        # 点列表里时开在第一个点上。
        start_index = next(
            (index for index, point in enumerate(points) if point.id == start_id),
            0,
        )
        terminal_index = next(
            index for index, point in enumerate(points) if point.id == terminal.point_id
        )
        first_reachable_day = 0 if terminal_index >= start_index else 1
        if terminal.day_index < first_reachable_day:
            raise ValueError(
                f"terminal_point 从开局时刻不可达: {terminal.point_id} 最早出现在第 "
                f"{first_reachable_day} 天，声明的却是第 {terminal.day_index} 天"
            )
        return self


__all__ = [
    "DAY_SEGMENTS",
    "DEFAULT_TIME_POINTS",
    "IDENTIFIER_PATTERN",
    "NIGHT_SEGMENTS",
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
    "InitialCustodySpec",
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
    "RuleSpecV3",
    "RuleStepSpec",
    "RuleTriggerSpec",
    "TargetKind",
    "TerminalTimePointSpec",
    "TimeOfDayQuery",
    "TimePointSpec",
    "TimeSegment",
    "TimeTaskSpec",
    "TimeTaskTargetSpec",
    "TravelCostSpec",
    "WorldProfileSpec",
    "default_label_for",
    "matches_time_query",
    "segment_at_hour",
]
