"""A-owned ports for durable ActionPlan orchestration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionPlanProgressEvent,
    AdjudicationExecution,
    AdjudicationStatusView,
    GetAdjudicationStatusRequest,
    SubmitAdjudicationRequest,
)
from collaboration_framework.host.schemas import ActionPlanRun, ActionPlanStepContext
from collaboration_framework.host.schemas.action_plan import (
    ActionPlanNarrationContext,
)


class ActionPlanStoreError(RuntimeError):
    code: str

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class ActionPlanConflictError(ActionPlanStoreError):
    pass


class ActionPlanVersionConflictError(ActionPlanStoreError):
    pass


class ActionPlanBusyError(ActionPlanStoreError):
    pass


class ActionPlanRunStore(Protocol):
    async def create(self, run: ActionPlanRun) -> ActionPlanRun: ...

    async def load(self, room_id: str, parent_action_id: str) -> ActionPlanRun | None: ...

    async def load_active_for_player(
        self,
        room_id: str,
        player_id: str,
    ) -> ActionPlanRun | None: ...

    async def load_active_for_room(self, room_id: str) -> ActionPlanRun | None: ...

    async def compare_and_swap(
        self,
        *,
        expected_run_version: int,
        updated_run: ActionPlanRun,
    ) -> ActionPlanRun: ...

    async def claim(
        self,
        *,
        room_id: str,
        parent_action_id: str,
        worker_id: str,
        now: datetime,
        lease_expires_at: datetime,
    ) -> ActionPlanRun: ...


class ActionPlanStepAdjudicator(Protocol):
    """Generate one proposal from only the current step and latest PlayerView."""

    async def adjudicate(self, context: ActionPlanStepContext) -> ActionAdjudication: ...


@dataclass(frozen=True)
class ActionPlanStepFailure:
    """步骤裁决失败的进程内诊断信息，不进入持久化模型或玩家协议。"""

    correlation_id: str
    plan_id: str
    step_id: str
    step_index: int
    attempt: int
    duration_ms: int
    code: str
    error: BaseException
    completed_steps: int
    authoritative_submitted: bool = False


class SingleAdjudicationExecutor(Protocol):
    async def submit(self, request: SubmitAdjudicationRequest) -> AdjudicationExecution: ...

    async def get_status(
        self,
        request: GetAdjudicationStatusRequest,
    ) -> AdjudicationStatusView: ...


class ActionPlanNarrationModelPort(Protocol):
    async def generate(
        self,
        context: ActionPlanNarrationContext,
    ) -> object: ...


ActionPlanProgressObserver = Callable[[ActionPlanProgressEvent], Awaitable[None]]
ActionPlanStepFailureObserver = Callable[[ActionPlanStepFailure], Awaitable[None]]
