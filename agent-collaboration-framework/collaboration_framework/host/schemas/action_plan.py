"""A-owned durable ActionPlan workflow state and safe step contexts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionPlan,
    ActionPlanPolicy,
    ActionPlanStep,
    AdjudicationExecution,
    ContractModel,
    PlayerInput,
    PlayerView,
)

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


class ActionPlanStepRun(ContractModel):
    step_id: str = Field(min_length=1, max_length=100)
    step_request_id: str = Field(min_length=1, max_length=200)
    step: ActionPlanStep
    status: PlanStepStatus = "pending"
    source_revision: str | None = Field(default=None, min_length=1)
    adjudication: ActionAdjudication | None = None
    adjudication_execution: AdjudicationExecution | None = None
    event_refs: tuple[str, ...] = ()
    pending_action_request_id: str | None = Field(default=None, min_length=1)
    safe_failure_code: str | None = Field(default=None, min_length=1, max_length=100)
    retry_count: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_state(self) -> ActionPlanStepRun:
        if self.adjudication is not None:
            if self.adjudication.request_id != self.step_request_id:
                raise ValueError("step adjudication request_id 与 step_request_id 不一致")
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
        if self.status == "waiting_for_player" and self.pending_action_request_id is None:
            raise ValueError("waiting_for_player step 必须记录 pending action request")
        return self


class ActionPlanRun(ContractModel):
    plan_id: str = Field(min_length=1, max_length=100)
    parent_action_id: str = Field(min_length=1, max_length=200)
    parent_input_fingerprint: str = Field(min_length=64, max_length=64)
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    created_revision: str = Field(min_length=1)
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
    created_at: datetime
    updated_at: datetime

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
    event_refs: tuple[str, ...] = ()


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
        return self


class ActionPlanAdvanceResult(ContractModel):
    run: ActionPlanRun
    player_view: PlayerView
    latest_execution: AdjudicationExecution | None = None


class SingleActionTurnResult(ContractModel):
    execution: AdjudicationExecution
    player_view: PlayerView


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
    allowed_evidence_refs: tuple[str, ...] = ()

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
        return self


class ActionPlanNarrationOutput(ContractModel):
    kind: Literal["narration", "clarification"] = "narration"
    text: str = Field(min_length=1)
    claimed_evidence_refs: tuple[str, ...] = ()
    suggested_actions: tuple[str, ...] = Field(default=(), max_length=3)
