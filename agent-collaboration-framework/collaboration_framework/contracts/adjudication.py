"""ModuleContent v3 single-intent adjudication contracts.

These models form the stable hand-off between an Agent-owned semantic decision
and the deterministic Rule Engine.  They intentionally contain high-level
domain effects instead of arbitrary state paths.
"""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import (
    Field,
    JsonValue,
    PrivateAttr,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from .common import ContractModel

CheckDifficulty: TypeAlias = Literal["regular", "hard", "extreme"]  # noqa: UP040
CheckDegree: TypeAlias = Literal[  # noqa: UP040
    "critical_success",
    "extreme_success",
    "hard_success",
    "regular_success",
    "failure",
    "fumble",
]
PersistenceIntent: TypeAlias = Literal[  # noqa: UP040
    "none",
    "character_state",
    "object_state",
    "inventory",
    "location",
]


class ActionTarget(ContractModel):
    kind: Literal["information", "entity", "location", "actor", "world"]
    id: str = Field(min_length=1)


class ActionMethod(ContractModel):
    family: str = Field(min_length=1)
    description: str = Field(min_length=1)


class SkillCheckCandidate(ContractModel):
    candidate_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    difficulty: CheckDifficulty
    method_summary: str = Field(min_length=1)
    player_safe_reason: str = Field(min_length=1)


class NoAdjudicationCheck(ContractModel):
    mode: Literal["none"] = "none"
    candidates: tuple[()] = ()


class RequiredAdjudicationCheck(ContractModel):
    mode: Literal["required"] = "required"
    candidates: tuple[SkillCheckCandidate, ...] = Field(min_length=1, max_length=1)


class PlayerChoiceAdjudicationCheck(ContractModel):
    mode: Literal["player_choice"] = "player_choice"
    candidates: tuple[SkillCheckCandidate, ...] = Field(min_length=2)


AdjudicationCheck = Annotated[
    NoAdjudicationCheck | RequiredAdjudicationCheck | PlayerChoiceAdjudicationCheck,
    Field(discriminator="mode"),
]


class RevealInformationEffect(ContractModel):
    type: Literal["reveal_information"] = "reveal_information"
    information_id: str = Field(min_length=1)
    scope: Literal["party", "actor"] = "party"


class HideInformationEffect(ContractModel):
    type: Literal["hide_information"] = "hide_information"
    information_id: str = Field(min_length=1)
    scope: Literal["party", "actor"] = "party"


class SetVisibilityEffect(ContractModel):
    type: Literal["set_visibility"] = "set_visibility"
    target_kind: Literal["information", "entity", "location"]
    target_id: str = Field(min_length=1)
    visible: bool
    scope: Literal["party", "actor"] = "party"


class EnterLocationEffect(ContractModel):
    type: Literal["enter_location"] = "enter_location"
    location_id: str = Field(min_length=1)


class EnsureRuntimeLocationEffect(ContractModel):
    type: Literal["ensure_runtime_location"] = "ensure_runtime_location"
    location_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    parent_location_id: str | None = Field(default=None, min_length=1)
    connected_location_id: str = Field(min_length=1)


class EnsureRuntimeEntityEffect(ContractModel):
    type: Literal["ensure_runtime_entity"] = "ensure_runtime_entity"
    entity_id: str = Field(min_length=1)
    entity_kind: Literal["npc", "object"]
    name: str = Field(min_length=1)
    location_id: str = Field(min_length=1)


class MoveEntityEffect(ContractModel):
    type: Literal["move_entity"] = "move_entity"
    entity_id: str = Field(min_length=1)
    location_id: str | None = Field(default=None, min_length=1)
    holder_actor_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def validate_destination(self) -> MoveEntityEffect:
        if (self.location_id is None) == (self.holder_actor_id is None):
            raise ValueError(
                "move_entity 必须且只能指定 location_id 或 holder_actor_id"
            )
        return self


class ChangeEntityStateEffect(ContractModel):
    type: Literal["change_entity_state"] = "change_entity_state"
    entity_id: str = Field(min_length=1)
    key: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    value: JsonValue


class ConsumeEntityEffect(ContractModel):
    type: Literal["consume_entity"] = "consume_entity"
    entity_id: str = Field(min_length=1)


class MarkCoreResolvedEffect(ContractModel):
    type: Literal["mark_core_resolved"] = "mark_core_resolved"


class SetEndingAvailabilityEffect(ContractModel):
    type: Literal["set_ending_availability"] = "set_ending_availability"
    available: bool


class CommitTerminalEndingEffect(ContractModel):
    type: Literal["commit_terminal_ending"] = "commit_terminal_ending"
    ending_id: str = Field(min_length=1)


class NarrativeOnlyEffect(ContractModel):
    type: Literal["narrative_only"] = "narrative_only"


class AdvanceWorldTimeEffect(ContractModel):
    """Jump the room to the single next point on the discrete timeline (#245).

    One effect is exactly one jump — the timeline decides *where*, the caller
    only decides *that*. Sleeping from noon until 20:00 is therefore two of
    these in sequence, and each one publishes its own `time.point_entered`, so
    a Rule that watches for nightfall still fires on the point it was written
    against instead of being skipped over.

    `to_point_id` is not a destination request: it is the Agent stating which
    point it believes comes next, and the Engine refuses the effect when that
    disagrees with the authored timeline.
    """

    type: Literal["advance_world_time"] = "advance_world_time"
    to_point_id: str | None = Field(default=None, min_length=1)


ActionEffect = Annotated[
    RevealInformationEffect
    | HideInformationEffect
    | SetVisibilityEffect
    | EnterLocationEffect
    | EnsureRuntimeLocationEffect
    | EnsureRuntimeEntityEffect
    | MoveEntityEffect
    | ChangeEntityStateEffect
    | ConsumeEntityEffect
    | MarkCoreResolvedEffect
    | SetEndingAvailabilityEffect
    | CommitTerminalEndingEffect
    | AdvanceWorldTimeEffect
    | NarrativeOnlyEffect,
    Field(discriminator="type"),
]


class RuleDecisionRef(ContractModel):
    """The Agent's answer to a Rule Match View question (#226 §2).

    Both ids are opaque: they come from the candidate menu the Engine published,
    and the Agent may not invent them. Naming a rule hands ownership of the
    outcome to that rule — `success_effects` / `failure_effects` on the same
    adjudication are then ignored, because the published rule owns what the
    result does (`effect_authority: rule`, #226 §5).
    """

    rule_id: str = Field(min_length=1, max_length=100)
    option_id: str = Field(min_length=1, max_length=100)


class ActionAdjudication(ContractModel):
    """One Agent-adjudicated intent; the Engine never splits or interprets it."""

    request_id: str = Field(min_length=1, max_length=200)
    source_revision: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    target: ActionTarget
    method: ActionMethod
    # 旧裁决缺少该字段时按 none 恢复；模型侧 Prompt 会要求新输出必须显式填写。
    persistence_intent: PersistenceIntent = "none"
    check: AdjudicationCheck
    rule_decision: RuleDecisionRef | None = None
    success_effects: tuple[ActionEffect, ...] = ()
    failure_effects: tuple[ActionEffect, ...] = ()
    _persistence_intent_explicit: bool = PrivateAttr(default=False)

    @model_validator(mode="after")
    def validate_candidates(self) -> ActionAdjudication:
        # 私有标记随 model_copy 保留，但不会进入持久化 JSON 或公开 Schema。
        object.__setattr__(
            self,
            "_persistence_intent_explicit",
            "persistence_intent" in self.model_fields_set,
        )
        ids = [candidate.candidate_id for candidate in self.check.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate_id 必须在一次 ActionAdjudication 内唯一")
        return self

    @property
    def persistence_intent_explicit(self) -> bool:
        """区分旧 JSON 的兼容默认值与新模型显式声明。"""

        return self._persistence_intent_explicit

    @model_serializer(mode="wrap")
    def serialize_with_legacy_intent_compatibility(
        self,
        handler: SerializerFunctionWrapHandler,
    ) -> dict[str, object]:
        """旧裁决继续省略意图字段，新裁决则保留显式 none 供重载后校验。"""

        payload = handler(self)
        if not self.persistence_intent_explicit:
            payload.pop("persistence_intent", None)
        return payload


class SubmitAdjudicationRequest(ContractModel):
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    adjudication: ActionAdjudication


class PendingCheckOption(ContractModel):
    candidate_id: str = Field(min_length=1)
    skill_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    target_value: int = Field(ge=0, le=100)
    difficulty: CheckDifficulty
    method_summary: str = Field(min_length=1)
    player_safe_reason: str = Field(min_length=1)


class PendingCheckDecisionView(ContractModel):
    decision_id: str = Field(min_length=1)
    status: Literal["awaiting_skill_choice"] = "awaiting_skill_choice"
    action_request_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    decision_version: int = Field(ge=1)
    actor_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    options: tuple[PendingCheckOption, ...] = Field(min_length=1)
    allow_cancel: Literal[True] = True


class SelectCheckChoice(ContractModel):
    kind: Literal["select"] = "select"
    candidate_id: str = Field(min_length=1)


class CancelCheckChoice(ContractModel):
    kind: Literal["cancel"] = "cancel"


CheckChoice = Annotated[
    SelectCheckChoice | CancelCheckChoice, Field(discriminator="kind")
]


class CheckDecisionRequest(ContractModel):
    request_id: str = Field(min_length=1, max_length=200)
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    decision_id: str = Field(min_length=1)
    decision_version: int = Field(ge=1)
    choice: CheckChoice


class CheckRoll(ContractModel):
    value: int = Field(ge=1, le=100)
    degree: CheckDegree
    passed: bool


class AcceptResultOption(ContractModel):
    option_id: str = Field(min_length=1)
    kind: Literal["accept_result"] = "accept_result"


class SpendResourceOption(ContractModel):
    option_id: str = Field(min_length=1)
    kind: Literal["spend_resource"] = "spend_resource"
    resource_id: Literal["luck"] = "luck"
    cost: int = Field(ge=1)
    result_degree: CheckDegree


class PushOption(ContractModel):
    option_id: str = Field(min_length=1)
    kind: Literal["push"] = "push"
    requires_revised_method: Literal[True] = True
    player_safe_risk_summary: str = Field(min_length=1)


PostRollOption = Annotated[
    AcceptResultOption | SpendResourceOption | PushOption,
    Field(discriminator="kind"),
]


class CheckRunView(ContractModel):
    check_id: str = Field(min_length=1)
    action_request_id: str = Field(min_length=1)
    selected_candidate_id: str = Field(min_length=1)
    # 这三项此前只在引擎内部的 CheckRun 上，视图不带，于是「这次检定用了什么
    # 技能、目标值多少」跨不出引擎：带 post-roll 选项的检定最终结算发生在
    # 玩家做完奖惩骰决定那一轮，那时技能选择阶段的 PendingCheckDecisionView
    # 已经不在了，调用方无从重建。视图自带这三项后，任何一轮都能独立描述自己。
    selected_skill_id: str = Field(min_length=1)
    selected_skill_name: str = Field(min_length=1)
    difficulty: CheckDifficulty
    target_value: int = Field(ge=0, le=100)
    status: Literal["awaiting_post_roll_decision", "resolved"]
    version: int = Field(ge=1)
    roll_count: int = Field(ge=1, le=2)
    roll: CheckRoll
    post_roll_options: tuple[PostRollOption, ...] = ()
    final_result: CheckRoll | None = None


class PushAdjudication(ContractModel):
    method_description: str = Field(min_length=1, max_length=1000)


class PostRollDecisionRequest(ContractModel):
    request_id: str = Field(min_length=1, max_length=200)
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    check_id: str = Field(min_length=1)
    check_version: int = Field(ge=1)
    option_id: str = Field(min_length=1)
    push_adjudication: PushAdjudication | None = None


class CommittedResult(ContractModel):
    """玩家安全的已提交结果摘要，不复制原始事件载荷或内部裁决信息。"""

    kind: PersistenceIntent
    target_id: str = Field(min_length=1)
    state_key: str | None = Field(default=None, min_length=1)
    state_value: JsonValue | None = None
    event_ref: str = Field(min_length=1)


class NarrationEvidence(ContractModel):
    """玩家可见的公开事件语义，供主持人叙述时引用。"""

    ref: str = Field(min_length=1)
    kind: Literal["entity_discovered"]
    subject_id: str = Field(min_length=1)
    subject_name: str = Field(min_length=1)
    subject_aliases: tuple[str, ...] = ()
    description: str = ""
    required_in_narration: bool = False


class AdjudicationExecution(ContractModel):
    request_id: str = Field(min_length=1)
    action_request_id: str = Field(min_length=1)
    status: Literal[
        "awaiting_skill_choice",
        "awaiting_post_roll_decision",
        "resolved",
        "cancelled",
    ]
    view_revision: str = Field(min_length=1)
    outcome: Literal["success", "failure", "cancelled", "pending"]
    pending_decision: PendingCheckDecisionView | None = None
    check_run: CheckRunView | None = None
    event_refs: tuple[str, ...] = ()
    public_event_refs: tuple[str, ...] = ()
    # 只保存已提交且玩家可见的高层结果，供 Narrator 约束持久状态声明。
    committed_results: tuple[CommittedResult, ...] = ()
    narration_evidence: tuple[NarrationEvidence, ...] = ()

    @model_validator(mode="after")
    def validate_status_payload(self) -> AdjudicationExecution:
        if self.status == "awaiting_skill_choice" and self.pending_decision is None:
            raise ValueError("awaiting_skill_choice 必须包含 pending_decision")
        if self.status == "awaiting_post_roll_decision" and self.check_run is None:
            raise ValueError("awaiting_post_roll_decision 必须包含 check_run")
        if not set(self.public_event_refs).issubset(self.event_refs):
            raise ValueError("public_event_refs 必须是 event_refs 的子集")
        evidence_refs = tuple(item.ref for item in self.narration_evidence)
        if len(evidence_refs) != len(set(evidence_refs)):
            raise ValueError("narration_evidence ref 不得重复")
        if not set(evidence_refs).issubset(self.public_event_refs):
            raise ValueError("narration_evidence 必须引用 public_event_refs")
        return self


class AdjudicationRecovery(ContractModel):
    """Safe application-facing recovery projection for one adjudication."""

    action_request_id: str = Field(min_length=1, max_length=200)
    actor_id: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    execution: AdjudicationExecution
