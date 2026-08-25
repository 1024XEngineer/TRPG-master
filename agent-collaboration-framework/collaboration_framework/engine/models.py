"""Member-B internal state, Event, and execution-result models."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from pydantic import Field, JsonValue

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionEffect,
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
    TimeSegment,
    TravelInterrupted,
    ValidationResult,
    segment_at_hour,
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


class WorldTimePoint(ContractModel):
    """An exact hour on the world calendar (#245 §二.2)."""

    day_index: int = Field(default=0, ge=0)
    hour_of_day: int = Field(default=0, ge=0, le=23)

    @property
    def absolute_hour(self) -> int:
        """Total ordering across days, so "next point" is a plain comparison."""

        return self.day_index * 24 + self.hour_of_day


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

    # 默认落在正午而不是午夜：v2 房间没有 time_policy，起点是任选的，而没有
    # 存过时段的房间按小时回退——午夜会让"没声明时间的房间一开局就是夜里"。
    # v3 房间一律由 initial_state.start_time_point_id 覆盖这个默认值。
    current: WorldTimePoint = Field(
        default_factory=lambda: WorldTimePoint(day_index=0, hour_of_day=12)
    )
    current_point_id: str = Field(default="hour_12", min_length=1)
    # 模组声明的时段，在**推进时**解析完存进来（#415 §阶段一）。
    #
    # 谓词签名是 `(args, GameState, actor_id) -> bool`，拿不到
    # `module_content`，所以模组逐点声明的 `time_segment` 不可能在谓词里
    # 查表。加宽签名会动整个谓词注册表契约，连带 #401 的 E7 数值谓词；
    # 存进运行态则与既有的 `current_point_id` 同构。
    #
    # 可空是为了既有房间：它们的快照里没有这个字段，读取时按小时回退，
    # 下一次推进后写入解析值。
    current_time_segment: TimeSegment | None = None

    @property
    def time_segment(self) -> TimeSegment:
        """当前时段：存过就用存的，没存过按小时回退。"""

        return self.current_time_segment or segment_at_hour(self.current.hour_of_day)


class TimePointOccurrence(ContractModel):
    """时间线上的一次具体到达（#245 §一.5 / #415 §阶段四）。

    默认点每天都会来一次，剧情临时点只来一次。两者用**同一套绝对时间排序**，
    所以「15:00 的任务插在 12 与 18 之间」不需要任何特殊分支——把临时点混进
    默认点再按 `absolute_hour` 重排就是了。

    `point_id` 为 None 表示这一刻不对应任何模组声明的点，只由 TimeTask 排出来。
    那条路径拿不到 `TimePointSpec`，玩家措辞因此回退到 `time_segment` 的缺省值。
    """

    occurrence_id: str = Field(min_length=1)
    point_id: str | None = Field(default=None, min_length=1)
    day_index: int = Field(ge=0)
    hour_of_day: int = Field(ge=0, le=23)
    time_segment: TimeSegment
    origin: Literal["default", "time_task"] = "time_task"

    @property
    def absolute_hour(self) -> int:
        return self.day_index * 24 + self.hour_of_day


class RuntimeTimeTask(ContractModel):
    """一个已经排好、等着到期的定时任务（#245 §5）。

    #245 冻结了这个形状，但类一直不存在——只在 `engine/timeline.py` 的注释里
    被提过一次。任务绑到 occurrence 而不是绑到时刻，因为同日同小时的多个任务
    共享同一个 occurrence：取消其中一个不该动其他任务，也不该动那个点。
    """

    task_id: str = Field(min_length=1)
    task_key: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    branch_id: str = Field(min_length=1)
    occurrence_id: str = Field(min_length=1)
    priority: int = 0
    visibility: Literal["public", "hidden"] = "public"
    # `completed` 之后不会再发第二次 `time.task_due`：单次发布靠的是「把状态
    # 翻成 completed」和「发事件」落在同一次提交里，而不是靠调用方自觉。
    status: Literal["scheduled", "completed", "cancelled"] = "scheduled"
    bindings: dict[str, JsonValue] = Field(default_factory=dict)
    # 取消时记下来的原因码，进审计事件。
    cancel_reason_code: str | None = Field(default=None, min_length=1)


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


class AgendaParentContinuation(ContractModel):
    """父动作里还没执行的那一半，等规则链稳定后接着跑（#398 §阶段二）。

    事件屏障要求「规则没结算完就不能执行下一个效果」，所以一次动作可能停在
    效果序列中间。这里保存的就是停下时剩的部分：Agenda 恢复后按原顺序补完，
    或者被规则取消掉。

    `completion_emitted` 区分「停在效果之间」和「效果都跑完了、卡在
    `action.succeeded` 触发的规则上」——后者不能再补发一次完成事件。
    """

    passed: bool
    remaining_effects: tuple[ActionEffect, ...] = ()
    completion_emitted: bool = False


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
    parent_continuation: AgendaParentContinuation | None = None
    # 挂起时游标还没读到的 DomainEvent。规则在挂起前已经发过 `rule.triggered`
    # 和自己前置效果的事件，恢复时那些事件不在新的 events 列表里，不带走就
    # 永远不会被匹配。只有在途 Agenda 落库，所以它随 Agenda 一起消失；上界由
    # 既有的 `max_steps` 约束，不另设预算。
    carried_events: tuple[DomainEvent, ...] = ()
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
    # 只保存**临时** occurrence：默认点每天都会来，从 module_content 现推就行，
    # 存一份等于把模组内容复制进房间状态，换版本时必然漂移。
    time_occurrences: dict[str, TimePointOccurrence] = Field(default_factory=dict)
    time_tasks: dict[str, RuntimeTimeTask] = Field(default_factory=dict)
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


class RuleCheckOrigin(ContractModel):
    """把一次检定钉回它所属的 Agenda 游标（#398 §阶段三）。

    被动检定不是玩家发起的，是规则走到 `CheckStep` 时引擎替规则问的。结算之后
    要恢复的也不是「这次行动的成功/失败效果」，而是**同一条规则的
    `result_routes` 分支**——所以必须记住是哪个 Agenda、哪条规则、哪个分支、
    哪一步、由哪个事件触发。

    不另加恢复令牌：`PendingCheckDecision.decision_version` 已经承担版本与恢复
    职责，再加一个只会多出一个可能不同步的事实源。
    """

    agenda_id: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    branch_id: str = Field(min_length=1)
    step_id: str = Field(min_length=1)
    source_event_id: str = Field(min_length=1)


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
    # 非空即「这是规则拥有的检定」：结算走 result_routes，不走 adjudication 的
    # success/failure 效果。
    rule_origin: RuleCheckOrigin | None = None
    allow_cancel: bool = True

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
            allow_cancel=self.allow_cancel,
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
