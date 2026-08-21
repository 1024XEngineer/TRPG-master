"""Public contracts for finite, sequential ActionPlan orchestration."""

from __future__ import annotations

from typing import Annotated, Literal, TypeAlias

from pydantic import Field, model_validator

from .adjudication import ActionAdjudication, AdjudicationExecution
from .common import ContractError, ContractModel

ActionPlanStepKind: TypeAlias = Literal[
    "travel",
    "wait",
    "rest",
    "action",
    "dialogue",
]


class ActionPlanStep(ContractModel):
    """One player-safe semantic goal; it contains no future adjudication."""

    kind: ActionPlanStepKind
    semantic_goal: str = Field(min_length=1, max_length=1000)
    public_progress_label: str | None = Field(
        default=None, min_length=1, max_length=200
    )


class ActionPlan(ContractModel):
    """A variable-length, finite and strictly sequential player plan."""

    kind: Literal["action_plan"] = "action_plan"
    goal: str = Field(min_length=1, max_length=2000)
    steps: tuple[ActionPlanStep, ...] = Field(min_length=1)


class SingleActionDecision(ContractModel):
    kind: Literal["single_action"] = "single_action"
    adjudication: ActionAdjudication


HostTurnDecision = Annotated[
    SingleActionDecision | ActionPlan,
    Field(discriminator="kind"),
]


class ActionPlanPolicy(ContractModel):
    """A frozen runtime policy, not a product-level schema length limit."""

    policy_schema_version: Literal[1] = 1
    max_plan_steps: int = Field(default=32, ge=1, le=1024)
    max_steps_per_advance: int = Field(default=3, ge=1, le=1024)
    max_repair_attempts: int = Field(default=1, ge=0, le=8)

    @model_validator(mode="after")
    def validate_window(self) -> ActionPlanPolicy:
        if self.max_steps_per_advance > self.max_plan_steps:
            # A one-step policy is a valid runtime policy even though the
            # product default window is three. Clamp the scheduling window to
            # the plan ceiling while preserving the ge=1 invariant.
            object.__setattr__(self, "max_steps_per_advance", self.max_plan_steps)
        return self

    def require_plan(self, plan: ActionPlan) -> None:
        if len(plan.steps) > self.max_plan_steps:
            raise ActionPlanPolicyError(
                "PLAN_TOO_LARGE",
                f"计划包含 {len(plan.steps)} 个步骤，超过当前技术上限 "
                f"{self.max_plan_steps}；请拆分或缩小目标",
            )


class ActionPlanPolicyError(ContractError):
    """Stable policy rejection raised before any authoritative step executes."""

    def __init__(self, code: str, public_message: str) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message


class GetAdjudicationStatusRequest(ContractModel):
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    action_request_id: str = Field(min_length=1, max_length=200)


class CancelActionPlanRequest(ContractModel):
    request_id: str = Field(min_length=1, max_length=200)
    room_id: str = Field(min_length=1)
    player_id: str = Field(min_length=1)
    actor_id: str = Field(min_length=1)
    parent_action_id: str = Field(min_length=1, max_length=200)


class AdjudicationStatusView(ContractModel):
    """Player-safe recovery projection for one single-intent adjudication."""

    action_request_id: str = Field(min_length=1)
    status: Literal[
        "not_submitted",
        "awaiting_skill_choice",
        "awaiting_post_roll_decision",
        "awaiting_time_consent",
        "awaiting_scene_consent",
        "resolved",
        "cancelled",
    ]
    execution: AdjudicationExecution | None = None

    @model_validator(mode="after")
    def validate_execution(self) -> AdjudicationStatusView:
        if self.status == "not_submitted":
            if self.execution is not None:
                raise ValueError("not_submitted 不得包含 execution")
            return self
        if self.execution is None or self.execution.status != self.status:
            raise ValueError("adjudication status 必须与 execution 一致")
        if self.execution.action_request_id != self.action_request_id:
            raise ValueError("execution 不属于请求的 action_request_id")
        return self


class ActionPlanProgressEvent(ContractModel):
    """Public progress contains no raw plan, effects, tools or hidden context."""

    type: Literal[
        "plan.started",
        "plan.step_changed",
        "plan.stopped",
        "plan.completed",
    ]
    correlation_id: str = Field(min_length=1)
    current_step: int = Field(ge=0)
    completed_steps: int = Field(ge=0)
    total_steps: int = Field(ge=1)
    phase: Literal[
        "understanding",
        "executing",
        "waiting_for_player",
        "completed",
        "stopped",
    ]
    public_progress_label: str | None = Field(
        default=None, min_length=1, max_length=200
    )
    safe_reason: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_counts(self) -> ActionPlanProgressEvent:
        if (
            self.current_step > self.total_steps
            or self.completed_steps > self.total_steps
        ):
            raise ValueError("plan progress 计数超过 total_steps")
        return self
