"""A-owned durable ActionPlan workflow state and safe step contexts."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from collaboration_framework.contracts import (
    ActionAdjudication,
    CommittedResult,
    ActionPlan,
    ActionPlanPolicy,
    ActionPlanStep,
    AdjudicationExecution,
    ContractModel,
    JsonObject,
    KeeperCapabilityView,
    NarrationEvidence,
    PlayerInput,
    PlayerView,
    ValidationFeedback,
    WorldClockView,
)
from collaboration_framework.host.schemas.agent import _validate_keeper_scope
from collaboration_framework.host.schemas.history import RecentTurnContext

PlanRunStatus = Literal[
    "active",
    "checkpointed",
    "waiting_for_player",
    "needs_clarification",
    "retryable_failure",
    "awaiting_narration",
    "completed",
    "cancelled",
    "stopped",
]
PlanStepStatus = Literal[
    "pending",
    "adjudicating",
    "ready",
    "waiting_for_player",
    "completed",
    "stopped",
]

TERMINAL_PLAN_STATUSES = frozenset({"completed", "cancelled", "stopped"})
RESERVING_PLAN_STATUSES = frozenset(
    {
        "active",
        "checkpointed",
        "waiting_for_player",
        "needs_clarification",
        "retryable_failure",
        "awaiting_narration",
    }
)

# 房间行动占用必须能自己过期，理由与 RoomActionLockManager 里那条 🔴 注释相同：
# 一次失败若没走到释放路径，房间就永久锁死，之后谁都无法再提交。进程内锁早就
# 照做了（60s），而这张持久化占用表当初漏了，于是把同一个失败模式重新引了回来。
#
# 取值不能照抄那 60s：`waiting_for_player` 也在 RESERVING_PLAN_STATUSES 里，
# 玩家正在挑技能、决定要不要烧幸运时计划就停在这个状态。太短会在人还在思考时
# 抽走占用，随后 CAS 抛 PLAN_RESERVATION_LOST 把回合打死——比它要修的 bug 更糟。
RESERVATION_TTL = timedelta(minutes=5)


def reservation_is_expired(
    reserved_at: datetime, *, now: datetime | None = None
) -> bool:
    """占用是否已过期到可以被别人接管。

    `reserved_at` 允许是 naive 的：SQLite 不保存时区，取回来的列即使声明了
    `timezone=True` 也是 naive，直接跟 aware 的当前时间相减会抛 TypeError。
    这里统一按 UTC 解释，两个 store 就不用各写一遍。
    """

    moment = now if now is not None else datetime.now(UTC)
    if reserved_at.tzinfo is None:
        reserved_at = reserved_at.replace(tzinfo=UTC)
    return moment - reserved_at > RESERVATION_TTL


class ActionPlanStepRun(ContractModel):
    step_id: str = Field(min_length=1, max_length=100)
    step_request_id: str = Field(min_length=1, max_length=200)
    step: ActionPlanStep
    status: PlanStepStatus = "pending"
    source_revision: str | None = Field(default=None, min_length=1)
    adjudication: ActionAdjudication | None = None
    adjudication_execution: AdjudicationExecution | None = None
    # The clock this step left behind, sampled from the PlayerView refreshed
    # right after it committed. None on rows persisted before this field existed
    # and on steps that never executed.
    world_time_after: WorldClockView | None = None
    event_refs: tuple[str, ...] = ()
    pending_action_request_id: str | None = Field(default=None, min_length=1)
    safe_failure_code: str | None = Field(default=None, min_length=1, max_length=100)
    retry_count: int = Field(default=0, ge=0)
    repair_attempts: int = Field(default=0, ge=0, le=8)
    last_validation_code: str | None = Field(default=None, min_length=1, max_length=100)
    last_validation_message: str | None = Field(default=None, min_length=1, max_length=512)
    # Player-safe repair comparison state. Stored in the existing PlanRun JSON
    # so a process restart cannot lose the original proposal and bypass the
    # semantic check before the repaired proposal reaches the Engine.
    repair_baseline: ActionAdjudication | None = None
    repair_feedback: ValidationFeedback | None = None

    @model_validator(mode="after")
    def validate_state(self) -> ActionPlanStepRun:
        if (self.last_validation_code is None) != (self.last_validation_message is None):
            raise ValueError("last_validation_code/message 必须同时存在或同时为空")
        if (self.repair_baseline is None) != (self.repair_feedback is None):
            raise ValueError("repair_baseline/feedback 必须同时存在或同时为空")
        if self.adjudication is not None:
            if self.adjudication.request_id != self.step_request_id:
                raise ValueError(
                    "step adjudication request_id 与 step_request_id 不一致"
                )
            if self.source_revision != self.adjudication.source_revision:
                raise ValueError("step source_revision 与 adjudication 不一致")
        if self.adjudication_execution is not None:
            if self.adjudication_execution.action_request_id != self.step_request_id:
                raise ValueError("step execution 不属于当前 step_request_id")
            if self.event_refs != self.adjudication_execution.event_refs:
                raise ValueError("step event_refs 与 execution 不一致")
        if (
            self.status in {"ready", "waiting_for_player", "completed"}
            and self.adjudication is None
        ):
            raise ValueError(f"{self.status} step 必须冻结 adjudication")
        if (
            self.status in {"waiting_for_player", "completed"}
            and self.adjudication_execution is None
        ):
            raise ValueError(f"{self.status} step 必须包含 execution")
        if (
            self.status == "waiting_for_player"
            and self.pending_action_request_id is None
        ):
            raise ValueError("waiting_for_player step 必须记录 pending action request")
        return self


class ActionPlanRun(ContractModel):
    plan_id: str = Field(min_length=1, max_length=100)
    parent_action_id: str = Field(min_length=1, max_length=200)
    parent_input_fingerprint: str = Field(min_length=64, max_length=64)
    # The verbatim utterance the fingerprint above was computed from. Needed to
    # rebuild a fingerprint-matching PlayerInput on resume: `plan.goal` is a
    # model-authored paraphrase and is not guaranteed to match the original
    # text, so it cannot stand in for it. None only for rows persisted before
    # this field existed; resume falls back to the pre-fix (paraphrase) behavior
    # for those.
    parent_utterance: str | None = Field(default=None, min_length=1)
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    created_revision: str = Field(min_length=1)
    # The clock the turn opened on, before any step ran. Together with each
    # step's `world_time_after` it gives the Narrator the whole span, so a plan
    # whose first step advances time is still narrated from where it started.
    opening_world_time: WorldClockView | None = None
    plan_schema_version: Literal[1] = 1
    run_version: int = Field(default=1, ge=1)
    status: PlanRunStatus = "active"
    current_step_index: int = Field(default=0, ge=0)
    policy_snapshot: ActionPlanPolicy
    plan: ActionPlan
    steps: tuple[ActionPlanStepRun, ...] = Field(min_length=2)
    lease_owner: str | None = Field(default=None, min_length=1, max_length=200)
    lease_expires_at: datetime | None = None
    cancel_request_ids: tuple[str, ...] = ()
    # A post-roll cancel is a two-phase operation: persist this intent first,
    # then accept the already-authoritative roll and stop the remaining plan.
    # Keeping it on the run makes the operation recoverable across a crash.
    pending_cancel_request_id: str | None = Field(
        default=None, min_length=1, max_length=200
    )
    created_at: datetime
    updated_at: datetime

    def to_persistence_json_dict(self) -> JsonObject:
        """序列化可恢复的内部运行状态，并保留裁决字段来源信息。"""

        return self.model_dump(
            mode="json",
            context={"preserve_persistence_intent_explicit": True},
        )

    @classmethod
    def from_persistence_json_dict(cls, value: JsonObject) -> ActionPlanRun:
        """只在可信存储边界读取内部兼容标记。"""

        return cls.model_validate(
            value,
            context={"allow_persistence_intent_explicit_marker": True},
        )

    @model_validator(mode="after")
    def validate_run(self) -> ActionPlanRun:
        if len(self.steps) != len(self.plan.steps):
            raise ValueError("PlanRun steps 必须与 ActionPlan 一一对应")
        self.policy_snapshot.require_plan(self.plan)
        if self.current_step_index > len(self.steps):
            raise ValueError("current_step_index 超过步骤数量")
        for index, (step_run, plan_step) in enumerate(
            zip(self.steps, self.plan.steps, strict=True)
        ):
            if step_run.step != plan_step:
                raise ValueError(f"PlanRun step {index} 与 ActionPlan 不一致")
            if index < self.current_step_index and step_run.status != "completed":
                raise ValueError("PlanRun 游标之前的步骤必须全部完成")
            if index > self.current_step_index and step_run.status != "pending":
                raise ValueError("PlanRun 游标之后的步骤不得提前开始")
            if step_run.repair_attempts > self.policy_snapshot.max_repair_attempts:
                raise ValueError("step repair_attempts 超过冻结的修复预算")
        if self.current_step_index == len(self.steps):
            if any(step.status != "completed" for step in self.steps):
                raise ValueError("PlanRun 到达尾游标时必须完成全部步骤")
            if self.status not in {"awaiting_narration", "completed"}:
                raise ValueError("完成全部步骤后必须等待叙事或进入完成态")
        else:
            current_status = self.steps[self.current_step_index].status
            allowed_current_statuses = {
                "active": {"pending", "adjudicating", "ready"},
                "checkpointed": {"pending"},
                "waiting_for_player": {"waiting_for_player"},
                "needs_clarification": {"stopped"},
                "retryable_failure": {"pending"},
                "cancelled": {"stopped"},
                "stopped": {"stopped"},
            }
            allowed = allowed_current_statuses.get(self.status)
            if allowed is None or current_status not in allowed:
                raise ValueError("PlanRun 状态与当前步骤状态不一致")
        if (self.lease_owner is None) != (self.lease_expires_at is None):
            raise ValueError("lease_owner 与 lease_expires_at 必须同时存在或同时为空")
        if self.status in TERMINAL_PLAN_STATUSES and self.lease_owner is not None:
            raise ValueError("终态 PlanRun 不得持有 worker lease")
        if len(self.cancel_request_ids) != len(set(self.cancel_request_ids)):
            raise ValueError("cancel request id 必须唯一")
        if self.pending_cancel_request_id is not None:
            if self.pending_cancel_request_id in self.cancel_request_ids:
                raise ValueError("pending cancel request 不得已经完成")
            if self.status != "waiting_for_player" or self.current_step_index >= len(
                self.steps
            ):
                raise ValueError(
                    "pending cancel request 只能存在于等待玩家处理的当前步骤"
                )
            current = self.steps[self.current_step_index]
            if (
                current.status != "waiting_for_player"
                or current.adjudication_execution is None
                or current.adjudication_execution.status
                != "awaiting_post_roll_decision"
            ):
                raise ValueError(
                    "pending cancel request 必须对应等待 post-roll 的当前步骤"
                )
        return self

    @property
    def completed_steps(self) -> int:
        return sum(step.status == "completed" for step in self.steps)

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_PLAN_STATUSES


class CompletedPlanStepSummary(ContractModel):
    step_index: int = Field(ge=0)
    semantic_goal: str = Field(min_length=1, max_length=1000)
    outcome: Literal["success", "failure", "cancelled"]
    view_revision: str = Field(min_length=1)
    world_time_after: WorldClockView | None = None
    event_refs: tuple[str, ...] = ()
    narration_evidence: tuple[NarrationEvidence, ...] = ()
    committed_results: tuple[CommittedResult, ...] = ()

    @model_validator(mode="after")
    def validate_evidence(self) -> CompletedPlanStepSummary:
        if not {item.ref for item in self.narration_evidence}.issubset(self.event_refs):
            raise ValueError("步骤 narration_evidence 必须引用公开 event_refs")
        if not {item.event_ref for item in self.committed_results}.issubset(self.event_refs):
            raise ValueError("步骤 committed_results 必须引用公开 event_refs")
        return self


class ActionPlanStepContext(ContractModel):
    """Only the current semantic step receives the latest safe PlayerView."""

    player_input: PlayerInput
    plan_id: str = Field(min_length=1)
    plan_goal: str = Field(min_length=1)
    step_index: int = Field(ge=0)
    step_request_id: str = Field(min_length=1, max_length=200)
    step: ActionPlanStep
    player_view: PlayerView
    completed_steps: tuple[CompletedPlanStepSummary, ...] = ()
    # Player-safe presentation history is not authoritative world state.  It is
    # nevertheless useful as soft context when the player now acts on an
    # ordinary detail that was narrated in the same continuous scene; the
    # adjudicator must still materialize that detail through Runtime creation.
    recent_history: RecentTurnContext | None = None
    # Set only after the Engine refused a proposal for this same step. It carries
    # a stable player-safe code/reason, never hidden module content.
    #
    # 614 = 100 (`ValidationResult.code`) + 2 + 512 (`player_safe_reason`)，也就是
    # 一条拒绝理由本身的上限。#313 之后还要追加一段与具体 id 无关的静态修复指引
    # （`_REPAIR_HINTS`），所以留到 1024；`test_repair_hint_fits_the_step_context`
    # 用最长的那条钉住这个余量，加长指引会先撞到那个测试而不是线上。
    previous_rejection: str | None = Field(default=None, min_length=1, max_length=1024)
    # Controlled Keeper-side capability list for this same revision; see
    # HostAgentContext.keeper_capabilities. Never forwarded to the Narrator.
    keeper_capabilities: KeeperCapabilityView | None = None

    @model_validator(mode="after")
    def validate_scope(self) -> ActionPlanStepContext:
        if (
            self.player_input.room_id != self.player_view.room_id
            or self.player_input.player_id != self.player_view.player_id
            or self.player_input.actor_id != self.player_view.actor_id
        ):
            raise ValueError("ActionPlanStepContext identity scope 不一致")
        if self.step_index != len(self.completed_steps):
            raise ValueError("当前 step_index 必须紧跟已完成步骤")
        if self.recent_history is not None:
            self.recent_history.validate_for(
                player_input=self.player_input,
                player_view=self.player_view,
            )
        _validate_keeper_scope(self.keeper_capabilities, self.player_view)
        return self


class ActionPlanAdvanceResult(ContractModel):
    run: ActionPlanRun
    player_view: PlayerView
    latest_execution: AdjudicationExecution | None = None


class SingleActionTurnResult(ContractModel):
    execution: AdjudicationExecution
    player_view: PlayerView
    # Sampled before the adjudication was submitted; see ActionPlanRun.
    opening_world_time: WorldClockView | None = None


class SingleActionClarificationResult(ContractModel):
    """单动作两次裁决均未形成合法效果时的无提交结果。"""

    player_view: PlayerView
    player_safe_reason: str = Field(min_length=1, max_length=512)
    opening_world_time: WorldClockView | None = None


class ActionPlanNarrationContext(ContractModel):
    """Player-safe evidence for one final or partial ActionPlan narration."""

    background: str = Field(min_length=1)
    player_input: PlayerInput
    plan_id: str | None = Field(default=None, min_length=1)
    plan_goal: str = Field(min_length=1)
    termination_status: Literal[
        "resolved",
        "needs_clarification",
        "cancelled",
        "stopped",
    ]
    completed_steps: tuple[CompletedPlanStepSummary, ...] = ()
    player_view: PlayerView
    # `player_view` is the post-turn state, so it is the *only* clock the
    # Narrator would otherwise see. This is where the turn started; each step
    # then carries the clock it ended on.
    opening_world_time: WorldClockView | None = None
    allowed_evidence_refs: tuple[str, ...] = ()
    narration_evidence: tuple[NarrationEvidence, ...] = ()
    # Only populated for the bounded second narration attempt; contains no
    # hidden data, just the player-safe requirement the first output missed.
    narration_retry_hint: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_narration_scope(self) -> ActionPlanNarrationContext:
        if (
            self.player_input.room_id != self.player_view.room_id
            or self.player_input.player_id != self.player_view.player_id
            or self.player_input.actor_id != self.player_view.actor_id
        ):
            raise ValueError("ActionPlanNarrationContext identity scope 不一致")
        evidence = tuple(
            ref for step in self.completed_steps for ref in step.event_refs
        )
        if set(self.allowed_evidence_refs) != set(evidence):
            raise ValueError("allowed_evidence_refs 必须等于已完成步骤的公开 evidence")
        step_evidence = tuple(
            item for step in self.completed_steps for item in step.narration_evidence
        )
        if self.narration_evidence != step_evidence:
            raise ValueError("narration_evidence 必须按步骤聚合")
        result_refs = {
            result.event_ref
            for step in self.completed_steps
            for result in step.committed_results
        }
        if not result_refs.issubset(set(evidence)):
            raise ValueError("committed_results 必须引用对应步骤的公开 evidence")
        return self


class ActionPlanNarrationOutput(ContractModel):
    kind: Literal["narration", "clarification"] = "narration"
    text: str = Field(min_length=1)
    claimed_evidence_refs: tuple[str, ...] = ()
    suggested_actions: tuple[str, ...] = Field(default=(), max_length=3)
