"""编写阶段的 ModuleContent v3 契约（issues #212 / #226 / #240 / #245）。

这是 #212 §13 实施拆分中的第 1 项：定义公开的 v3 契约及其 JSON Schema。
它只定义**模组作者需要编写的内容**；运行时对应对象（RuleAgenda、WorldTimeState、
KnowledgeResolution、EndingDraft、DomainEventV3、ActorLocationState 等）属于后续工作，
因此有意不在此处定义。

最初单独建立此模块，是因为 #226 将迁移冻结为 *Breaking*，而 v2 的 `ModuleContent`
仍需作为迁移输入保留。现在该输入已经移除：所有发布的模组都是 v3，v1/v2 契约已在
#384 中删除。这里剩下的就是唯一的模组内容契约。

领域节点及其职责：

* `Information` / `Entity` / `Location` 是 Canon 世界节点（#212 §3.1）。
* `Rule` 是确定性的触发声明，而不是自然语言匹配器：`agent_match` 规则向 Agent
  提供不透明的候选菜单，`event` 规则匹配已经提交的领域事件（#226 §1–§2）。
* 编写阶段只定义 `ModuleTimePolicySpec`；世界时钟本身属于运行时状态（#245）。

两个根字段 `initial_state` 和 `world_profile` 虽在 #212 §3.1 中被命名，但四个 issue
都没有给出具体字段设计。这里仅按契约其余部分实际引用的内容建立最小模型，并在各自的
docstring 中标记为临时设计，便于后续 issue 扩展，而不必推翻当前的猜测。
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, JsonValue, model_validator

from .adjudication import ActionEffect, CheckDegree
from .common import ContractModel
from .inventory import ItemComponent

# --------------------------------------------------------------------------- #
# 面向玩家的发布元数据
#
# 这两个类原本住在 v1 的 contracts/module.py 里，但它们描述的是「模组怎么呈现
# 给玩家」，与 schema 版本无关，v3 一直在用（`ModuleContentV3.presentation`）。
# v1 契约删除时它们必须留下，所以先搬到这里 (#384)。
# --------------------------------------------------------------------------- #


class ModuleStoryPage(ContractModel):
    """创建角色前向玩家展示的安全页面。"""

    title: str = ""
    content: str = Field(min_length=1)


class ModulePresentation(ContractModel):
    """面向玩家的发布元数据，与主持人上下文分离。"""

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
# 共享词汇
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
# 信息（#212 §4.2）
# --------------------------------------------------------------------------- #


class InformationDiscoverySpec(ContractModel):
    """事实是否在开局隐藏，以及发现后与谁共享。"""

    initial: Literal["hidden", "known"] = "hidden"
    scope: Literal["party", "actor"] = "party"


class InformationAudienceSpec(ContractModel):
    keeper: bool = True
    player_when_discovered: bool = True


class InformationPresentationSpec(ContractModel):
    channels: tuple[Literal["narration", "journal", "handout"], ...] = ("narration",)
    show_in_ui: bool = True


class InformationRecoverySpec(ContractModel):
    """模组对通过*指定路径*获取事实的要求程度。

    `strict` 必须遵守声明的来源；`adaptive` / `guaranteed` 允许 Agent 通过合理的运行时
    来源（邻居、公共记录或代为查询的职员等）获得同一条 Canon 信息，但绝不允许它编造
    不属于 Canon 的事实（#212 §4.2、§4.3）。
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
    """一条 Canon 事实，与所有可能承载和提供它的对象分离。"""

    id: Identifier
    kind: Literal["clue", "fact", "rumor", "testimony", "record"] = "clue"
    title: str = Field(min_length=1, max_length=200)
    # 仅供 Keeper 使用的文本。绝不会投影到 PlayerView；Agent 只能通过受控的
    # Keeper 能力视图看到它。
    keeper_content: str = Field(min_length=1)
    # 事实公开后允许玩家阅读的内容。
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
    """队伍最终必须*知道的内容*，与获取这些内容的路径无关。"""

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
# 实体（#212 §8.2）
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
    """仅表示语义关系。

    `owns` / `carried_by` / `contains` 有意不表示物品保管关系：物品的权威位置由运行时
    `ItemCustody` 状态决定，容量、装备槽和堆叠规则目前也明确没有冻结（#212 §8.2）。
    """

    kind: EntityRelationKind
    target_id: Identifier


class EntitySpecV3(ContractModel):
    """一个 Canon 人物或物体。

    Agent 在会话中途提出的运行时实体不在这里编写；它们带有 `origin="runtime"`，存放在
    GameState 中，并且永远不能遮蔽 Canon ID（#212 §8.2）。
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
    # 受众与发现是两个独立概念。即使实体是 public，在已注册的确定性谓词确认其
    # 被发现之前，也可以不出现在任何玩家投影中。
    visibility_conditions: tuple[ConditionExpr, ...] = ()
    plot_relevance: bool = True
    lifecycle: Literal["campaign", "session"] = "campaign"


# --------------------------------------------------------------------------- #
# 地点（#212 §7.3）
# --------------------------------------------------------------------------- #


class LocationSpecV3(ContractModel):
    """一个地点。

    `parent_location_id` 用于驱动 UI 面包屑；可达性由独立的图（`LocationEdgeSpec`）表示。
    v2 将两者混为一谈，导致 Scene 出口无法表达“站在上锁的书房门口”（#212 §7.3、§7.4）。
    """

    id: Identifier
    kind: Literal["region", "site", "room", "connector"]
    origin: Literal["canon", "system_seeded"] = "canon"
    name: str = Field(min_length=1, max_length=200)
    player_visible_name: str = ""
    player_visible_description: str = ""
    aliases: tuple[str, ...] = Field(default=(), exclude_if=lambda value: not value)
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
    """导航图中的一条有向路径。

    `access_point_id` 是控制该路径的 Entity（例如门或闸）。设置该字段且实体处于锁定
    状态时，移动会停在边界处而不是直接失败，这样玩家可以处于“书房门口”，而不是已经
    进入书房或被当作无处可去。
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
# 规则条件（#226 §2）
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
    """已注册的谓词，绝不是脚本。

    #226 §1 禁止规则包含脚本、数据库路径和任意事件载荷；谓词名称必须解析到 Engine
    已注册的实现。
    """

    op: Literal["predicate"] = "predicate"
    predicate: str = Field(min_length=1, max_length=100, pattern=IDENTIFIER_PATTERN)
    args: dict[str, JsonValue] = Field(default_factory=dict)


ConditionExpr: TypeAlias = Annotated[
    AllCondition | AnyCondition | NotCondition | PredicateCondition,
    Field(discriminator="op"),
]


# --------------------------------------------------------------------------- #
# 规则触发器（#226 §2、#240 §5）
# --------------------------------------------------------------------------- #


class CandidateScopeSpec(ContractModel):
    """哪些情形可以将这条规则呈现为 Agent 候选。

    #226 将此字段写作 `scene_ids`；#240 §5 规定 scene 是叙事章节，不再是 Actor 位置的
    权威来源，因此 v3 改用 `location_ids` 限定范围。这也是将 `RuleMatchContextRefs`
    迁移到 `actor_location_id` / `target_location_id` 的同一项协调结果。
    """

    action_families: tuple[str, ...] = ()
    location_ids: tuple[Identifier, ...] = ()
    target_kinds: tuple[TargetKind, ...] = ()
    target_ids: tuple[Identifier, ...] = ()


class MatchQuestionSpec(ContractModel):
    kind: Literal["action_declaration", "method", "intent_relation"]
    semantic_hints: tuple[str, ...] = Field(min_length=1)


class MatchOptionAuthorSpec(ContractModel):
    """提供给 Agent 的一个不透明选项。

    Agent 只提交 `id`，不提交其他内容；选项到后果的映射只存在于服务端，因此即使模型
    被操纵或过度发挥，也不能自行选择结果（#226 §1 设计结论）。
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
    # `when` was added after existing v3 modules had already been published.
    # Keep the absent value out of serialized content so those immutable module
    # versions retain their original normalized payload and content hash.
    when: ConditionExpr | None = Field(default=None, exclude_if=lambda value: value is None)
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
    """匹配已提交的领域事件，而不是玩家的话语（#212 §3.3）。"""

    kind: Literal["event"] = "event"
    event_type: str = Field(min_length=1, max_length=100)
    when: ConditionExpr | None = None
    entry_branch_id: Identifier = "default"


RuleTriggerSpec: TypeAlias = Annotated[
    AgentMatchTriggerSpec | EventTriggerSpec,
    Field(discriminator="kind"),
]


# --------------------------------------------------------------------------- #
# 规则执行步骤（#226 §4、§5）
# --------------------------------------------------------------------------- #


class RuleCheckSpec(ContractModel):
    """由规则负责的检定，而不是由 Agent 提议的检定。

    `parameters` 只能携带指定 Check Profile 已注册的字段，规则不能重新定义系统的骰子
    运算规则（#226 §5）。
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
    """接管 Agent 已经为本次行动提出的检定。

    `effect_authority="rule"` 是关键：玩家选择技能，但检定结果如何产生效果由已发布的
    规则负责，而不是由 Agent 决定。
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
    """明确授权 NPC 执行行动；任何行动都不会隐式发生。"""

    id: Identifier
    kind: Literal["create_npc_action_opportunity"] = "create_npc_action_opportunity"
    entity_id: Identifier
    action_id: str = Field(min_length=1, max_length=100)
    next_step_id: Identifier


class CreateTimeTaskStep(ContractModel):
    """由 #245 所属的 Schema；在这里引用，以便规则可以安排时间任务。"""

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
    """向叙述器传递引用，而不是让它照抄一段 prose。"""

    id: Identifier
    kind: Literal["presentation"] = "presentation"
    presentation_id: Identifier
    next_step_id: Identifier


class AwaitPlayerInputStep(ContractModel):
    """暂停议程，直到玩家再次发言（#226 §4）。"""

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
    """该步骤可能将控制权交给的所有步骤 ID。"""

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
    """一条编写好的规则。

    它的不可变身份是 `(module_id, module_version, rule_id)`；运行中的会话会固定一个
    ModuleVersion，因此重新发布规则也不会改变正在执行的议程含义（#226 §1）。
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
            # agent_match 规则按选项 ID 路由：Agent 能选择的每个选项都必须落到已声明的
            # 分支上，否则选择该选项就会无路可走。
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
# 主线解决与结局（#212 §10.2）
# --------------------------------------------------------------------------- #


class CoreResolutionSpec(ContractModel):
    required_goal_ids: tuple[Identifier, ...] = ()
    completion: Literal["all", "any"] = "all"


class EndingPolicySpec(ContractModel):
    """达到主线解决状态后开放结局，但不会强制立即结束。

    `allow_continue_after_core_resolution` 用于修复 v2 在主线闭合的瞬间就结束会话的行为
    （#212 §1）。
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
# 时间政策（#245 §二.1）
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
    """离散时间点；时钟在时间点之间跳转，而不是连续滴答推进。"""

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
# 临时根字段（#212 §3.1 提到这些字段，但没有 issue 给出字段设计）
# --------------------------------------------------------------------------- #


class WorldProfileSpec(ContractModel):
    """Agent 提议运行时内容时必须遵守的设定约束。

    临时设计：#212 §7.5 只要求 Agent 提议的客栈“符合 world_profile”。这里按判断该要求
    所需的最小字段建模，后续 issue 可以直接扩展，而无需撤销当前人为引入的结构。
    """

    era: str = Field(default="", max_length=100)
    region: str = Field(default="", max_length=100)
    technology_level: str = Field(default="", max_length=100)
    tone: str = Field(default="", max_length=200)
    forbidden_content: tuple[str, ...] = ()


class ActorPlacementSpec(ContractModel):
    """调查者的起始位置。Actor 位置属于运行时状态（#240 §1）。"""

    location_id: Identifier


class InitialStateSpec(ContractModel):
    """开局时的世界快照。

    临时设计，原因与 `WorldProfileSpec` 相同：这里只建模本契约其余部分实际引用的字段。
    """

    start_location_id: Identifier
    default_actor_placement: ActorPlacementSpec | None = None
    revealed_information_ids: tuple[Identifier, ...] = ()
    start_time_point_id: Identifier | None = None
    entity_state: dict[Identifier, dict[str, JsonValue]] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 根模型
# --------------------------------------------------------------------------- #


class ModuleContentV3(ContractModel):
    """v3 模组文件（#212 §3.1）。

    这里只保存结构不变量；跨集合引用检查（例如目标是否引用真实的 Information、边是否
    引用真实的 Location）属于语义校验器。语义校验器可以一次报告所有问题，而不是遇到
    第一个问题就中止。
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
    "RuleSpecV3",
    "RuleStepSpec",
    "RuleTriggerSpec",
    "TargetKind",
    "TimePointSpec",
    "TravelCostSpec",
    "WorldProfileSpec",
]
