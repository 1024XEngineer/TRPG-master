"""Durable, revision-by-revision orchestration over the single-intent Engine."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionPlan,
    ActionPlanPolicy,
    ActionPlanPolicyError,
    ActionPlanProgressEvent,
    ActionPlanStep,
    AdjudicationExecution,
    AdjudicationValidationError,
    CancelActionPlanRequest,
    ContractError,
    GetAdjudicationStatusRequest,
    HostTurnDecision,
    KeeperCapabilityView,
    PlayerInput,
    PlayerView,
    SingleActionDecision,
    SubmitAdjudicationRequest,
    ValidationFeedback,
    WorldClockView,
    player_input_fingerprint,
)
from collaboration_framework.host.ports import (
    ActionPlanProgressObserver,
    ActionPlanRunStore,
    ActionPlanStepAdjudicator,
    ActionPlanStepFailure,
    ActionPlanStepFailureObserver,
    SingleAdjudicationExecutor,
)
from collaboration_framework.host.schemas import (
    TERMINAL_PLAN_STATUSES,
    ActionPlanAdvanceResult,
    ActionPlanNarrationContext,
    ActionPlanRun,
    ActionPlanStepContext,
    ActionPlanStepRun,
    CompletedPlanStepSummary,
    SingleActionTurnResult,
)

from .host_agent_intent_resolver import TurnExecutionError
from .player_view_projector import PlayerViewProjector

logger = logging.getLogger(__name__)


class ActionPlanOrchestrator:
    """A-owned Saga coordinator; the Engine never receives an ActionPlan."""

    def __init__(
        self,
        *,
        store: ActionPlanRunStore,
        adjudicator: ActionPlanStepAdjudicator,
        executor: SingleAdjudicationExecutor,
        player_view_projector: PlayerViewProjector,
        policy: ActionPlanPolicy | None = None,
        lease_seconds: int = 30,
        on_step_failure: ActionPlanStepFailureObserver | None = None,
    ) -> None:
        if lease_seconds < 1:
            raise ValueError("lease_seconds 必须大于 0")
        self._store = store
        self._adjudicator = adjudicator
        self._executor = executor
        self._player_view_projector = player_view_projector
        self._policy = policy or ActionPlanPolicy()
        self._lease_seconds = lease_seconds
        self._on_step_failure = on_step_failure

    @property
    def policy(self) -> ActionPlanPolicy:
        return self._policy

    @property
    def adjudicator(self) -> ActionPlanStepAdjudicator:
        return self._adjudicator

    async def start_or_resume(
        self,
        player_input: PlayerInput,
        *,
        plan: ActionPlan | None = None,
        worker_id: str | None = None,
        auto_continue: bool = True,
        on_progress: ActionPlanProgressObserver | None = None,
    ) -> ActionPlanAdvanceResult:
        worker = worker_id or f"worker-{uuid4().hex}"
        run, created = await self._load_or_create(player_input, plan)
        if created:
            await self._emit(
                on_progress,
                self._progress(run, "plan.started", "understanding"),
            )
        self._require_parent(run, player_input, plan)

        return await self._advance_loaded(
            player_input,
            run,
            worker=worker,
            on_progress=on_progress,
            auto_continue=auto_continue,
        )

    async def resume_owned(
        self,
        *,
        room_id: str,
        player_id: str,
        actor_id: str,
        parent_action_id: str,
        worker_id: str | None = None,
        on_progress: ActionPlanProgressObserver | None = None,
    ) -> ActionPlanAdvanceResult:
        """Resume a persisted owned Plan without requiring the raw utterance again."""

        run = await self._store.load(room_id, parent_action_id)
        if (
            run is None
            or run.player_id != player_id
            or run.actor_id != actor_id
            or run.parent_action_id != parent_action_id
        ):
            raise ActionPlanPolicyError("PLAN_NOT_FOUND", "没有属于当前玩家的行动计划")
        player_input = PlayerInput(
            room_id=room_id,
            player_id=player_id,
            actor_id=actor_id,
            client_action_id=parent_action_id,
            # `plan.goal` is a model-authored paraphrase of the original
            # utterance and will not generally reproduce parent_input_fingerprint
            # (see _require_parent below, called via _advance_loaded). Use the
            # verbatim utterance the fingerprint was actually computed from;
            # fall back to the paraphrase only for runs persisted before
            # parent_utterance existed.
            utterance=run.parent_utterance or run.plan.goal,
        )
        return await self._advance_loaded(
            player_input,
            run,
            worker=worker_id or f"worker-{uuid4().hex}",
            on_progress=on_progress,
            auto_continue=True,
        )

    async def _advance_loaded(
        self,
        player_input: PlayerInput,
        run: ActionPlanRun,
        *,
        worker: str,
        on_progress: ActionPlanProgressObserver | None,
        auto_continue: bool,
    ) -> ActionPlanAdvanceResult:

        latest: AdjudicationExecution | None = None
        while True:
            if run.status in {
                "completed",
                "cancelled",
                "stopped",
                "needs_clarification",
                "awaiting_narration",
            }:
                view = await self._player_view_projector.project(player_input)
                return ActionPlanAdvanceResult(
                    run=run,
                    player_view=view,
                    latest_execution=latest,
                )

            result = await self.advance_one_window(
                player_input,
                worker_id=worker,
                on_progress=on_progress,
            )
            run = result.run
            latest = result.latest_execution or latest
            if not auto_continue or run.status != "checkpointed":
                return result.model_copy(update={"latest_execution": latest})

            # A soft window is a persisted scheduling checkpoint, not a player
            # step limit. Yield before atomically claiming the same Plan again.
            await asyncio.sleep(0)

    async def advance_one_window(
        self,
        player_input: PlayerInput,
        *,
        worker_id: str,
        on_progress: ActionPlanProgressObserver | None = None,
    ) -> ActionPlanAdvanceResult:
        now = datetime.now(UTC)
        run = await self._store.claim(
            room_id=player_input.room_id,
            parent_action_id=player_input.client_action_id,
            worker_id=worker_id,
            now=now,
            lease_expires_at=now + timedelta(seconds=self._lease_seconds),
        )
        self._require_parent(run, player_input, None)
        latest: AdjudicationExecution | None = None
        completed_in_window = 0

        if run.status == "waiting_for_player":
            waiting_step_index = run.current_step_index
            run, latest = await self._reconcile_waiting(run, player_input)
            if run.status == "waiting_for_player":
                run = await self._release_lease(run)
                return ActionPlanAdvanceResult(
                    run=run,
                    player_view=await self._player_view_projector.project(player_input),
                    latest_execution=latest,
                )
            if run.current_step_index > waiting_step_index:
                completed_in_window = 1

        while run.status == "active":
            if run.current_step_index >= len(run.steps):
                run = await self._transition(
                    run,
                    status="awaiting_narration",
                    release_lease=True,
                )
                return ActionPlanAdvanceResult(
                    run=run,
                    player_view=await self._player_view_projector.project(player_input),
                    latest_execution=latest,
                )
            if completed_in_window >= run.policy_snapshot.max_steps_per_advance:
                run = await self._transition(
                    run,
                    status="checkpointed",
                    release_lease=True,
                )
                return ActionPlanAdvanceResult(
                    run=run,
                    player_view=await self._player_view_projector.project(player_input),
                    latest_execution=latest,
                )

            step_index = run.current_step_index
            step_run = run.steps[step_index]
            if step_run.status in {"pending", "adjudicating"}:
                run = await self._freeze_current_adjudication(run, player_input)
                if run.status != "active":
                    run = await self._release_lease(run)
                    return ActionPlanAdvanceResult(
                        run=run,
                        player_view=await self._player_view_projector.project(player_input),
                    )
                step_run = run.steps[step_index]

            await self._emit(
                on_progress,
                self._progress(
                    run,
                    "plan.step_changed",
                    "executing",
                    label=self._step_label(step_run),
                ),
            )
            rejection: Exception | None = None
            while True:
                rejection = None
                try:
                    assert step_run.adjudication is not None
                    latest = await self._executor.submit(
                        SubmitAdjudicationRequest(
                            room_id=run.room_id,
                            player_id=run.player_id,
                            adjudication=step_run.adjudication,
                        )
                    )
                    break
                except Exception as exc:
                    rejection = exc
                    status = await self._executor.get_status(
                        GetAdjudicationStatusRequest(
                            room_id=run.room_id,
                            player_id=run.player_id,
                            action_request_id=step_run.step_request_id,
                        )
                    )
                    if status.status != "not_submitted" and status.execution is not None:
                        latest = status.execution
                        rejection = None
                        break

                    if not isinstance(exc, AdjudicationValidationError):
                        break

                    feedback = exc.result.to_feedback()
                    if feedback.repairability == "requires_player_choice":
                        run = await self._stop_for_validation(
                            run,
                            feedback,
                            plan_status="needs_clarification",
                        )
                        break
                    if feedback.repairability == "hard_reject":
                        run = await self._stop_for_validation(
                            run,
                            feedback,
                            plan_status="stopped",
                        )
                        break
                    if step_run.repair_attempts >= run.policy_snapshot.max_repair_attempts:
                        run = await self._stop_for_validation(
                            run,
                            feedback,
                            plan_status="needs_clarification",
                            code="REPAIR_BUDGET_EXHAUSTED",
                        )
                        break

                    run = await self._prepare_repair(run, feedback)
                    run = await self._freeze_current_adjudication(run, player_input)
                    if run.status != "active":
                        run = await self._release_lease(run)
                        return ActionPlanAdvanceResult(
                            run=run,
                            player_view=await self._player_view_projector.project(player_input),
                        )
                    step_run = run.steps[step_index]

            if rejection is not None:
                if run.status in {"needs_clarification", "stopped"}:
                    run = await self._release_lease(run)
                    await self._emit(
                        on_progress,
                        self._progress(
                            run,
                            "plan.stopped",
                            "stopped",
                            reason=run.steps[step_index].safe_failure_code,
                        ),
                    )
                    return ActionPlanAdvanceResult(
                        run=run,
                        player_view=await self._player_view_projector.project(player_input),
                    )
                current_view = await self._player_view_projector.project(player_input)
                if (
                    step_run.source_revision is not None
                    and current_view.revision != step_run.source_revision
                ):
                    run = await self._mark_step_failure(
                        run,
                        plan_status="retryable_failure",
                        step_status="pending",
                        code="STEP_REVISION_CHANGED",
                    )
                    run = await self._release_lease(run)
                    await self._emit(
                        on_progress,
                        self._progress(
                            run,
                            "plan.stopped",
                            "stopped",
                            reason="STEP_REVISION_CHANGED",
                        ),
                    )
                    return ActionPlanAdvanceResult(
                        run=run,
                        player_view=current_view,
                    )
                run = await self._mark_step_failure(
                    run,
                    plan_status="needs_clarification",
                    step_status="stopped",
                    code="STEP_ADJUDICATION_REJECTED",
                )
                run = await self._release_lease(run)
                await self._emit(
                    on_progress,
                    self._progress(
                        run,
                        "plan.stopped",
                        "stopped",
                        reason="STEP_ADJUDICATION_REJECTED",
                    ),
                )
                return ActionPlanAdvanceResult(
                    run=run,
                    player_view=await self._player_view_projector.project(player_input),
                )

            assert latest is not None
            view = await self._player_view_projector.refresh_adjudication(
                player_input,
                latest,
            )
            run = await self._apply_execution(
                run,
                latest,
                world_time_after=WorldClockView.from_world(view.world),
            )
            if run.status == "waiting_for_player":
                run = await self._release_lease(run)
                await self._emit(
                    on_progress,
                    self._progress(
                        run,
                        "plan.step_changed",
                        "waiting_for_player",
                        label=self._step_label(run.steps[step_index]),
                    ),
                )
                return ActionPlanAdvanceResult(
                    run=run,
                    player_view=view,
                    latest_execution=latest,
                )
            if run.status == "cancelled":
                await self._emit(
                    on_progress,
                    self._progress(
                        run,
                        "plan.stopped",
                        "stopped",
                        reason="PLAN_CANCELLED",
                    ),
                )
                return ActionPlanAdvanceResult(
                    run=run,
                    player_view=view,
                    latest_execution=latest,
                )
            if run.status == "stopped":
                run = await self._release_lease(run)
                await self._emit(
                    on_progress,
                    self._progress(
                        run,
                        "plan.stopped",
                        "stopped",
                        reason=run.steps[step_index].safe_failure_code,
                    ),
                )
                return ActionPlanAdvanceResult(
                    run=run,
                    player_view=view,
                    latest_execution=latest,
                )

            completed_in_window += 1
            await self._emit(
                on_progress,
                self._progress(
                    run,
                    "plan.step_changed",
                    "completed",
                    label=self._step_label(run.steps[step_index]),
                ),
            )

        run = await self._release_lease(run)
        return ActionPlanAdvanceResult(
            run=run,
            player_view=await self._player_view_projector.project(player_input),
            latest_execution=latest,
        )

    async def cancel_remaining(
        self,
        request: CancelActionPlanRequest,
        *,
        on_progress: ActionPlanProgressObserver | None = None,
    ) -> ActionPlanRun:
        run = await self._store.load(request.room_id, request.parent_action_id)
        if run is None:
            raise ActionPlanPolicyError("PLAN_NOT_FOUND", "没有可取消的行动计划")
        if run.player_id != request.player_id or run.actor_id != request.actor_id:
            raise ActionPlanPolicyError("PLAN_OWNER_MISMATCH", "行动计划不属于当前玩家")
        if request.request_id in run.cancel_request_ids or run.status == "cancelled":
            return run
        if run.is_terminal and run.status != "stopped":
            return run
        if run.status == "waiting_for_player":
            current = run.steps[run.current_step_index]
            status = await self._executor.get_status(
                GetAdjudicationStatusRequest(
                    room_id=run.room_id,
                    player_id=run.player_id,
                    action_request_id=current.step_request_id,
                )
            )
            if status.execution is not None and status.execution.status == "cancelled":
                run = await self._apply_execution(run, status.execution)
        if run.current_step_index < len(run.steps):
            current = run.steps[run.current_step_index]
            cancellable_boundary = (
                current.status == "pending"
                or (
                    run.status == "needs_clarification"
                    and current.status == "stopped"
                    and current.adjudication_execution is None
                )
                or (
                    current.status == "stopped"
                    and current.adjudication_execution is not None
                    and current.adjudication_execution.status == "cancelled"
                )
            )
            if not cancellable_boundary:
                raise ActionPlanPolicyError(
                    "PLAN_CANCEL_NOT_AT_BOUNDARY",
                    "当前步骤已经开始；请先完成或取消当前检定，再取消剩余计划",
                )
            steps = list(run.steps)
            steps[run.current_step_index] = current.model_copy(
                update={"status": "stopped", "safe_failure_code": "PLAN_CANCELLED"},
                deep=True,
            )
        else:
            steps = list(run.steps)
        now = datetime.now(UTC)
        cancelled = run.model_copy(
            update={
                "status": "cancelled",
                "steps": tuple(steps),
                "run_version": run.run_version + 1,
                "lease_owner": None,
                "lease_expires_at": None,
                "cancel_request_ids": (*run.cancel_request_ids, request.request_id),
                "updated_at": now,
            },
            deep=True,
        )
        cancelled = await self._store.compare_and_swap(
            expected_run_version=run.run_version,
            updated_run=cancelled,
        )
        await self._emit(
            on_progress,
            self._progress(
                cancelled,
                "plan.stopped",
                "stopped",
                reason="PLAN_CANCELLED",
            ),
        )
        return cancelled

    async def request_cancel_after_current(
        self,
        request: CancelActionPlanRequest,
    ) -> ActionPlanRun:
        """Persist a post-roll cancel intent without cancelling the check.

        The caller must settle the current check afterwards.  Persisting the
        intent first makes that settlement recoverable if the process exits
        between the two authoritative writes.
        """

        run = await self._store.load(request.room_id, request.parent_action_id)
        if run is None:
            raise ActionPlanPolicyError("PLAN_NOT_FOUND", "没有可取消的行动计划")
        if run.player_id != request.player_id or run.actor_id != request.actor_id:
            raise ActionPlanPolicyError("PLAN_OWNER_MISMATCH", "行动计划不属于当前玩家")
        if request.request_id in run.cancel_request_ids:
            return run
        if run.pending_cancel_request_id == request.request_id:
            return run
        if run.pending_cancel_request_id is not None:
            raise ActionPlanPolicyError(
                "PLAN_CANCEL_IN_PROGRESS",
                "当前行动计划已有一个取消请求正在处理",
            )
        if run.status != "waiting_for_player" or run.current_step_index >= len(run.steps):
            raise ActionPlanPolicyError(
                "PLAN_CANCEL_NOT_AT_BOUNDARY",
                "当前步骤已经开始；请先完成或取消当前检定，再取消剩余计划",
            )
        current = run.steps[run.current_step_index]
        status = await self._executor.get_status(
            GetAdjudicationStatusRequest(
                room_id=run.room_id,
                player_id=run.player_id,
                action_request_id=current.step_request_id,
            )
        )
        execution = status.execution
        if (
            current.status != "waiting_for_player"
            or execution is None
            or status.status != "awaiting_post_roll_decision"
            or execution.check_run is None
        ):
            raise ActionPlanPolicyError(
                "PLAN_CANCEL_NOT_AT_BOUNDARY",
                "当前步骤不在可接受检定结果的取消节点",
            )
        now = datetime.now(UTC)
        steps = list(run.steps)
        steps[run.current_step_index] = current.model_copy(
            update={
                "adjudication_execution": execution,
                "event_refs": execution.event_refs,
            },
            deep=True,
        )
        updated = run.model_copy(
            update={
                "steps": tuple(steps),
                "pending_cancel_request_id": request.request_id,
                "run_version": run.run_version + 1,
                "updated_at": now,
            },
            deep=True,
        )
        return await self._store.compare_and_swap(
            expected_run_version=run.run_version,
            updated_run=self._validated(updated),
        )

    async def mark_narration_completed(
        self,
        *,
        room_id: str,
        parent_action_id: str,
        on_progress: ActionPlanProgressObserver | None = None,
    ) -> ActionPlanRun:
        run = await self._store.load(room_id, parent_action_id)
        if run is None:
            raise ActionPlanPolicyError("PLAN_NOT_FOUND", "ActionPlanRun 不存在")
        if run.status == "completed":
            return run
        if run.status != "awaiting_narration":
            raise ActionPlanPolicyError(
                "PLAN_NOT_AWAITING_NARRATION",
                "行动计划尚未进入最终叙事阶段",
            )
        completed = await self._transition(run, status="completed", release_lease=True)
        await self._emit(
            on_progress,
            self._progress(completed, "plan.completed", "completed"),
        )
        return completed

    async def active_for_room(self, room_id: str) -> ActionPlanRun | None:
        return await self._store.load_active_for_room(room_id)

    async def get_run(
        self,
        room_id: str,
        parent_action_id: str,
    ) -> ActionPlanRun | None:
        return await self._store.load(room_id, parent_action_id)

    async def build_narration_context(
        self,
        player_input: PlayerInput,
        *,
        verify_fingerprint: bool = True,
    ) -> ActionPlanNarrationContext:
        run = await self._store.load(
            player_input.room_id,
            player_input.client_action_id,
        )
        if run is None:
            raise ActionPlanPolicyError("PLAN_NOT_FOUND", "ActionPlanRun 不存在")
        if verify_fingerprint:
            self._require_parent(run, player_input, None)
        elif (
            run.room_id != player_input.room_id
            or run.player_id != player_input.player_id
            or run.actor_id != player_input.actor_id
            or run.parent_action_id != player_input.client_action_id
        ):
            raise ActionPlanPolicyError("PARENT_ACTION_CONFLICT", "行动计划 owner 不一致")
        termination_by_status: dict[
            str,
            Literal["resolved", "needs_clarification", "cancelled", "stopped"],
        ] = {
            "awaiting_narration": "resolved",
            "completed": "resolved",
            "needs_clarification": "needs_clarification",
            "cancelled": "cancelled",
            "stopped": "stopped",
        }
        termination = termination_by_status.get(run.status)
        if termination is None:
            raise ActionPlanPolicyError(
                "PLAN_NOT_READY_FOR_NARRATION",
                "行动计划尚未到达可叙事状态",
            )
        view = await self._player_view_projector.project(player_input)
        summaries = self._narration_summaries(run)
        evidence = tuple(ref for step in summaries for ref in step.event_refs)
        narration_evidence = tuple(
            item for step in summaries for item in step.narration_evidence
        )
        return ActionPlanNarrationContext(
            background=view.background,
            player_input=player_input,
            plan_id=run.plan_id,
            plan_goal=run.plan.goal,
            termination_status=termination,
            completed_steps=summaries,
            player_view=view,
            opening_world_time=run.opening_world_time,
            allowed_evidence_refs=evidence,
            narration_evidence=narration_evidence,
        )

    async def _load_or_create(
        self,
        player_input: PlayerInput,
        plan: ActionPlan | None,
    ) -> tuple[ActionPlanRun, bool]:
        existing = await self._store.load(
            player_input.room_id,
            player_input.client_action_id,
        )
        if existing is not None:
            return existing, False
        if plan is None:
            raise ActionPlanPolicyError(
                "PLAN_NOT_FOUND",
                "没有可恢复的行动计划",
            )
        self._policy.require_plan(plan)
        view = await self._player_view_projector.project(player_input)
        now = datetime.now(UTC)
        plan_id = self._stable_id(
            "plan",
            player_input.room_id,
            player_input.client_action_id,
        )
        steps = tuple(
            ActionPlanStepRun(
                step_id=self._stable_id("step", plan_id, str(index)),
                step_request_id=self._stable_id(
                    "plan-step-v1",
                    player_input.client_action_id,
                    str(index),
                ),
                step=step,
            )
            for index, step in enumerate(plan.steps)
        )
        run = ActionPlanRun(
            plan_id=plan_id,
            parent_action_id=player_input.client_action_id,
            parent_input_fingerprint=player_input_fingerprint(player_input),
            parent_utterance=player_input.utterance,
            room_id=player_input.room_id,
            player_id=player_input.player_id,
            actor_id=player_input.actor_id,
            created_revision=view.revision,
            opening_world_time=WorldClockView.from_world(view.world),
            policy_snapshot=self._policy,
            plan=plan,
            steps=steps,
            created_at=now,
            updated_at=now,
        )
        created = await self._store.create(run)
        return created, created == run

    async def _keeper_capabilities(
        self,
        player_input: PlayerInput,
        view: PlayerView,
    ) -> KeeperCapabilityView | None:
        """Read the Keeper capability list, degrading to None if unavailable.

        A source that does not implement it (offline fakes, older adapters) must
        not break adjudication: without it the Agent simply keeps the smaller,
        player-safe vocabulary it had before.
        """

        try:
            return await self._player_view_projector.keeper_capabilities(
                player_input,
                expected_revision=view.revision,
            )
        except (AttributeError, NotImplementedError):
            return None

    async def _freeze_current_adjudication(
        self,
        run: ActionPlanRun,
        player_input: PlayerInput,
    ) -> ActionPlanRun:
        index = run.current_step_index
        steps = list(run.steps)
        current = steps[index]
        if current.status == "pending":
            steps[index] = current.model_copy(
                update={"status": "adjudicating"},
                deep=True,
            )
            run = await self._replace_steps(run, tuple(steps))
            current = run.steps[index]
        view = await self._player_view_projector.project(player_input)
        context = ActionPlanStepContext(
            player_input=player_input,
            plan_id=run.plan_id,
            plan_goal=run.plan.goal,
            step_index=index,
            step_request_id=current.step_request_id,
            step=current.step,
            player_view=view,
            completed_steps=self._completed_summaries(run),
            previous_rejection=self._validation_feedback_text(current),
            keeper_capabilities=await self._keeper_capabilities(player_input, view),
        )
        adjudication_started_at = time.monotonic()
        try:
            proposal = await self._adjudicator.adjudicate(context)
        except TurnExecutionError as exc:
            await self._observe_step_failure(
                run,
                current,
                code=exc.code,
                error=exc.__cause__ or exc,
                started_at=adjudication_started_at,
            )
            return await self._mark_step_failure(
                run,
                plan_status="retryable_failure" if exc.retryable else "needs_clarification",
                step_status="pending" if exc.retryable else "stopped",
                code=exc.code,
            )
        except Exception as exc:
            await self._observe_step_failure(
                run,
                current,
                code="STEP_ADJUDICATOR_FAILED",
                error=exc,
                started_at=adjudication_started_at,
            )
            return await self._mark_step_failure(
                run,
                plan_status="retryable_failure",
                step_status="pending",
                code="STEP_ADJUDICATOR_FAILED",
            )

        adjudication = proposal.model_copy(
            update={
                "request_id": current.step_request_id,
                "source_revision": view.revision,
                "actor_id": run.actor_id,
            },
            deep=True,
        )
        steps = list(run.steps)
        steps[index] = current.model_copy(
            update={
                "status": "ready",
                "source_revision": view.revision,
                "adjudication": adjudication,
                "safe_failure_code": None,
            },
            deep=True,
        )
        return await self._replace_steps(run, tuple(steps))

    async def _prepare_repair(
        self,
        run: ActionPlanRun,
        feedback: ValidationFeedback,
    ) -> ActionPlanRun:
        index = run.current_step_index
        steps = list(run.steps)
        current = steps[index]
        steps[index] = current.model_copy(
            update={
                "status": "pending",
                "source_revision": None,
                "adjudication": None,
                "adjudication_execution": None,
                "event_refs": (),
                "pending_action_request_id": None,
                "safe_failure_code": None,
                "repair_attempts": current.repair_attempts + 1,
                "last_validation_code": feedback.code,
                "last_validation_message": feedback.player_safe_reason,
            },
            deep=True,
        )
        return await self._replace_steps(run, tuple(steps))

    async def _stop_for_validation(
        self,
        run: ActionPlanRun,
        feedback: ValidationFeedback,
        *,
        plan_status: str,
        code: str | None = None,
    ) -> ActionPlanRun:
        index = run.current_step_index
        steps = list(run.steps)
        current = steps[index]
        steps[index] = current.model_copy(
            update={
                "status": "stopped",
                "source_revision": None,
                "adjudication": None,
                "adjudication_execution": None,
                "event_refs": (),
                "pending_action_request_id": None,
                "safe_failure_code": code or feedback.code,
                "last_validation_code": feedback.code,
                "last_validation_message": feedback.player_safe_reason,
            },
            deep=True,
        )
        return await self._replace_steps(run, tuple(steps), status=plan_status)

    @staticmethod
    def _validation_feedback_text(step: ActionPlanStepRun) -> str | None:
        if step.last_validation_code is None or step.last_validation_message is None:
            return None
        return f"{step.last_validation_code}: {step.last_validation_message}"

    async def _observe_step_failure(
        self,
        run: ActionPlanRun,
        step: ActionPlanStepRun,
        *,
        code: str,
        error: BaseException,
        started_at: float,
    ) -> None:
        """尽力上报步骤诊断；观察器故障绝不能改变权威状态机的收束结果。"""

        if self._on_step_failure is None:
            return
        failure = ActionPlanStepFailure(
            correlation_id=run.parent_action_id,
            plan_id=run.plan_id,
            step_id=step.step_id,
            step_index=run.current_step_index,
            attempt=step.retry_count + 1,
            duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
            code=code,
            error=error,
            completed_steps=sum(item.status == "completed" for item in run.steps),
        )
        try:
            await self._on_step_failure(failure)
        except Exception:
            # 诊断链路必须 fail-open，否则日志系统故障会覆盖玩家真正遇到的失败。
            logger.warning("action plan step failure observer raised", exc_info=True)

    async def _reconcile_waiting(
        self,
        run: ActionPlanRun,
        player_input: PlayerInput,
    ) -> tuple[ActionPlanRun, AdjudicationExecution | None]:
        step = run.steps[run.current_step_index]
        status = await self._executor.get_status(
            GetAdjudicationStatusRequest(
                room_id=run.room_id,
                player_id=run.player_id,
                action_request_id=step.step_request_id,
            )
        )
        if status.status in {"awaiting_skill_choice", "awaiting_post_roll_decision"}:
            return run, status.execution
        if status.execution is None:
            failed = await self._mark_step_failure(
                run,
                plan_status="needs_clarification",
                step_status="stopped",
                code="PENDING_ADJUDICATION_MISSING",
            )
            return failed, None
        view = await self._player_view_projector.refresh_adjudication(
            player_input,
            status.execution,
        )
        return (
            await self._apply_execution(
                run,
                status.execution,
                world_time_after=WorldClockView.from_world(view.world),
            ),
            status.execution,
        )

    async def _apply_execution(
        self,
        run: ActionPlanRun,
        execution: AdjudicationExecution,
        *,
        world_time_after: WorldClockView | None = None,
    ) -> ActionPlanRun:
        index = run.current_step_index
        current = run.steps[index]
        steps = list(run.steps)
        common = {
            "adjudication_execution": execution,
            "event_refs": execution.event_refs,
            "pending_action_request_id": None,
            "safe_failure_code": None,
            # A step that stops halfway keeps whatever clock it managed to
            # commit; only a caller with no refreshed view leaves it untouched.
            "world_time_after": world_time_after or current.world_time_after,
        }
        if execution.status in {
            "awaiting_skill_choice",
            "awaiting_post_roll_decision",
        }:
            steps[index] = current.model_copy(
                update={
                    **common,
                    "status": "waiting_for_player",
                    "pending_action_request_id": current.step_request_id,
                },
                deep=True,
            )
            return await self._replace_steps(
                run,
                tuple(steps),
                status="waiting_for_player",
            )
        if execution.status == "cancelled" or execution.outcome in {"failure", "cancelled"}:
            code = "STEP_CANCELLED" if execution.status == "cancelled" else "STEP_FAILED"
            steps[index] = current.model_copy(
                update={**common, "status": "stopped", "safe_failure_code": code},
                deep=True,
            )
            return await self._replace_steps(
                run,
                tuple(steps),
                status="stopped",
                consume_cancel_request=run.pending_cancel_request_id is not None,
            )

        steps[index] = current.model_copy(
            update={**common, "status": "completed"},
            deep=True,
        )
        next_index = index + 1
        if run.pending_cancel_request_id is not None:
            if next_index < len(steps):
                steps[next_index] = steps[next_index].model_copy(
                    update={
                        "status": "stopped",
                        "safe_failure_code": "PLAN_CANCELLED",
                    },
                    deep=True,
                )
                return await self._replace_steps(
                    run,
                    tuple(steps),
                    current_step_index=next_index,
                    status="cancelled",
                    consume_cancel_request=True,
                )
            return await self._replace_steps(
                run,
                tuple(steps),
                current_step_index=next_index,
                status="awaiting_narration",
                consume_cancel_request=True,
            )
        return await self._replace_steps(
            run,
            tuple(steps),
            current_step_index=next_index,
            status=("awaiting_narration" if next_index == len(steps) else "active"),
        )

    async def _mark_step_failure(
        self,
        run: ActionPlanRun,
        *,
        plan_status: str,
        step_status: str,
        code: str,
    ) -> ActionPlanRun:
        index = run.current_step_index
        steps = list(run.steps)
        current = steps[index]
        update: dict[str, object] = {
            "status": step_status,
            "safe_failure_code": code,
            "retry_count": current.retry_count + 1,
        }
        if step_status == "pending":
            update.update(
                {
                    "source_revision": None,
                    "adjudication": None,
                    "adjudication_execution": None,
                    "event_refs": (),
                    "pending_action_request_id": None,
                }
            )
        steps[index] = current.model_copy(update=update, deep=True)
        return await self._replace_steps(run, tuple(steps), status=plan_status)

    async def _replace_steps(
        self,
        run: ActionPlanRun,
        steps: tuple[ActionPlanStepRun, ...],
        *,
        status: str | None = None,
        current_step_index: int | None = None,
        consume_cancel_request: bool = False,
    ) -> ActionPlanRun:
        now = datetime.now(UTC)
        next_status = status or run.status
        # A terminal run must not keep a worker lease — `ActionPlanRun` refuses
        # that combination outright. Dropping the lease here rather than in a
        # follow-up `_release_lease` matters because this write is what a store
        # persists: a store that validates on read (the SQLAlchemy one does)
        # could no longer load the row it had just written, so the follow-up
        # release would fail too and leave the run permanently unreadable.
        release_lease = next_status in TERMINAL_PLAN_STATUSES
        update: dict[str, object] = {
            "steps": steps,
            "status": next_status,
            "current_step_index": (
                run.current_step_index if current_step_index is None else current_step_index
            ),
            "run_version": run.run_version + 1,
            "lease_owner": None if release_lease else run.lease_owner,
            "lease_expires_at": None if release_lease else run.lease_expires_at,
            "updated_at": now,
        }
        if consume_cancel_request:
            request_id = run.pending_cancel_request_id
            if request_id is not None and request_id not in run.cancel_request_ids:
                update["cancel_request_ids"] = (*run.cancel_request_ids, request_id)
            update["pending_cancel_request_id"] = None
        updated = run.model_copy(
            update=update,
            deep=True,
        )
        return await self._store.compare_and_swap(
            expected_run_version=run.run_version,
            updated_run=self._validated(updated),
        )

    async def _transition(
        self,
        run: ActionPlanRun,
        *,
        status: str,
        release_lease: bool,
    ) -> ActionPlanRun:
        now = datetime.now(UTC)
        drop_lease = release_lease or status in TERMINAL_PLAN_STATUSES
        updated = run.model_copy(
            update={
                "status": status,
                "run_version": run.run_version + 1,
                "lease_owner": None if drop_lease else run.lease_owner,
                "lease_expires_at": None if drop_lease else run.lease_expires_at,
                "updated_at": now,
            },
            deep=True,
        )
        return await self._store.compare_and_swap(
            expected_run_version=run.run_version,
            updated_run=self._validated(updated),
        )

    @staticmethod
    def _validated(run: ActionPlanRun) -> ActionPlanRun:
        """Fail at the writer, not on the next read.

        `model_copy(update=...)` does not re-run validators, so a broken
        invariant would otherwise be persisted silently and only surface when
        some later request tries to load the row — by then the failure is
        unattributable and the run is stuck.
        """

        return ActionPlanRun.model_validate(run.model_dump(mode="json"))

    async def _release_lease(self, run: ActionPlanRun) -> ActionPlanRun:
        if run.lease_owner is None:
            return run
        return await self._transition(run, status=run.status, release_lease=True)

    @staticmethod
    def _require_parent(
        run: ActionPlanRun,
        player_input: PlayerInput,
        plan: ActionPlan | None,
    ) -> None:
        if (
            run.room_id != player_input.room_id
            or run.player_id != player_input.player_id
            or run.actor_id != player_input.actor_id
            or run.parent_action_id != player_input.client_action_id
            or run.parent_input_fingerprint != player_input_fingerprint(player_input)
        ):
            raise ActionPlanPolicyError(
                "PARENT_ACTION_CONFLICT",
                "同一 parent action id 已绑定到不同输入或所有者",
            )
        if plan is not None and run.plan != plan:
            raise ActionPlanPolicyError(
                "PARENT_ACTION_CONFLICT",
                "同一 parent action id 已绑定到不同计划",
            )

    @staticmethod
    def _completed_summaries(run: ActionPlanRun) -> tuple[CompletedPlanStepSummary, ...]:
        summaries: list[CompletedPlanStepSummary] = []
        for index, step in enumerate(run.steps[: run.current_step_index]):
            execution = step.adjudication_execution
            if step.status != "completed" or execution is None:
                raise ContractError("PlanRun 游标之前存在未完成步骤")
            if execution.outcome == "pending":
                raise ContractError("已完成 PlanRun 步骤不得保留 pending outcome")
            summaries.append(
                CompletedPlanStepSummary(
                    step_index=index,
                    semantic_goal=step.step.semantic_goal,
                    outcome=execution.outcome,
                    view_revision=execution.view_revision,
                    world_time_after=step.world_time_after,
                    event_refs=execution.public_event_refs,
                    narration_evidence=execution.narration_evidence,
                )
            )
        return tuple(summaries)

    @staticmethod
    def _narration_summaries(
        run: ActionPlanRun,
    ) -> tuple[CompletedPlanStepSummary, ...]:
        summaries = list(ActionPlanOrchestrator._completed_summaries(run))
        if run.current_step_index < len(run.steps):
            step = run.steps[run.current_step_index]
            execution = step.adjudication_execution
            if step.status == "stopped" and execution is not None:
                if execution.outcome == "pending":
                    raise ContractError("已停止 PlanRun 步骤不得保留 pending outcome")
                summaries.append(
                    CompletedPlanStepSummary(
                        step_index=run.current_step_index,
                        semantic_goal=step.step.semantic_goal,
                        outcome=execution.outcome,
                        view_revision=execution.view_revision,
                        world_time_after=step.world_time_after,
                        event_refs=execution.public_event_refs,
                        narration_evidence=execution.narration_evidence,
                    )
                )
        return tuple(summaries)

    @staticmethod
    def _stable_id(namespace: str, *parts: str) -> str:
        canonical = "\x1f".join((namespace, *parts))
        return f"{namespace}-{hashlib.sha256(canonical.encode()).hexdigest()[:40]}"

    @staticmethod
    def _step_label(step: ActionPlanStepRun) -> str:
        return (
            step.step.public_progress_label
            or {
                "travel": "正在前往目标地点",
                "wait": "正在等待",
                "rest": "正在休息",
                "action": "正在执行行动",
                "dialogue": "正在与目标交谈",
            }[step.step.kind]
        )

    @staticmethod
    def _progress(
        run: ActionPlanRun,
        event_type: Literal[
            "plan.started",
            "plan.step_changed",
            "plan.stopped",
            "plan.completed",
        ],
        phase: Literal[
            "understanding",
            "executing",
            "waiting_for_player",
            "completed",
            "stopped",
        ],
        *,
        label: str | None = None,
        reason: str | None = None,
    ) -> ActionPlanProgressEvent:
        current = min(run.current_step_index + 1, len(run.steps))
        return ActionPlanProgressEvent(
            type=event_type,
            correlation_id=run.parent_action_id,
            current_step=current,
            completed_steps=run.completed_steps,
            total_steps=len(run.steps),
            phase=phase,
            public_progress_label=label,
            safe_reason=reason,
        )

    @staticmethod
    async def _emit(
        observer: ActionPlanProgressObserver | None,
        event: ActionPlanProgressEvent,
    ) -> None:
        if observer is not None:
            try:
                await observer(event)
            except Exception:
                # Progress is an optional, player-safe projection. Delivery
                # failure must never change or duplicate authoritative steps.
                return


class HostTurnDecisionExecutor:
    """Dispatch single actions directly and plans through the durable coordinator."""

    def __init__(
        self,
        *,
        plan_orchestrator: ActionPlanOrchestrator,
        executor: SingleAdjudicationExecutor,
        player_view_projector: PlayerViewProjector,
        repair_adjudicator: ActionPlanStepAdjudicator | None = None,
        policy: ActionPlanPolicy | None = None,
    ) -> None:
        self._plan_orchestrator = plan_orchestrator
        self._executor = executor
        self._player_view_projector = player_view_projector
        self._repair_adjudicator = repair_adjudicator
        self._policy = policy or ActionPlanPolicy()

    async def execute(
        self,
        player_input: PlayerInput,
        decision: HostTurnDecision,
        *,
        on_progress: ActionPlanProgressObserver | None = None,
    ) -> SingleActionTurnResult | ActionPlanAdvanceResult:
        if isinstance(decision, ActionPlan):
            return await self._plan_orchestrator.start_or_resume(
                player_input,
                plan=decision,
                on_progress=on_progress,
            )
        if not isinstance(decision, SingleActionDecision):
            raise TypeError("不支持的 HostTurnDecision")
        active = await self._plan_orchestrator.active_for_room(player_input.room_id)
        if active is not None:
            raise ActionPlanPolicyError(
                "ACTION_IN_PROGRESS",
                "当前房间已有未完成行动计划",
            )
        opening_view = await self._player_view_projector.project(player_input)
        view = opening_view
        adjudication = self._bind_single_adjudication(
            decision.adjudication,
            player_input=player_input,
            view=view,
        )
        repair_attempts = 0
        while True:
            try:
                execution = await self._executor.submit(
                    SubmitAdjudicationRequest(
                        room_id=player_input.room_id,
                        player_id=player_input.player_id,
                        adjudication=adjudication,
                    )
                )
                break
            except Exception as exc:
                status = await self._executor.get_status(
                    GetAdjudicationStatusRequest(
                        room_id=player_input.room_id,
                        player_id=player_input.player_id,
                        action_request_id=player_input.client_action_id,
                    )
                )
                if status.status != "not_submitted" and status.execution is not None:
                    execution = status.execution
                    break
                if not isinstance(exc, AdjudicationValidationError):
                    raise
                feedback = exc.result.to_feedback()
                if feedback.repairability not in {
                    "auto_repairable",
                    "retry_with_latest_revision",
                }:
                    raise
                if self._repair_adjudicator is None:
                    raise
                if repair_attempts >= self._policy.max_repair_attempts:
                    raise TurnExecutionError(
                        "REPAIR_BUDGET_EXHAUSTED",
                        "本次行动仍无法安全执行，需要玩家确认下一步",
                        retryable=False,
                    ) from exc
                repair_attempts += 1
                view = await self._player_view_projector.project(player_input)
                context = ActionPlanStepContext(
                    player_input=player_input,
                    plan_id="single-action",
                    plan_goal=decision.adjudication.summary,
                    step_index=0,
                    step_request_id=player_input.client_action_id,
                    step=ActionPlanStep(
                        kind=self._single_action_step_kind(decision.adjudication),
                        semantic_goal=decision.adjudication.summary,
                    ),
                    player_view=view,
                    previous_rejection=(
                        f"{feedback.code}: {feedback.player_safe_reason}"
                    ),
                    keeper_capabilities=await self._single_keeper_capabilities(
                        player_input,
                        view,
                    ),
                )
                proposal = await self._repair_adjudicator.adjudicate(context)
                adjudication = self._bind_single_adjudication(
                    proposal,
                    player_input=player_input,
                    view=view,
                )
        return SingleActionTurnResult(
            execution=execution,
            player_view=await self._player_view_projector.refresh_adjudication(
                player_input,
                execution,
            ),
            # `view` was projected before the submit above, so this is the clock
            # the action started on — a single "睡到晚上" moves it too.
            opening_world_time=WorldClockView.from_world(opening_view.world),
        )

    @staticmethod
    def _single_action_step_kind(
        adjudication: ActionAdjudication,
    ) -> Literal["travel", "wait", "rest", "action", "dialogue"]:
        family = adjudication.method.family
        if family == "travel":
            return "travel"
        if family == "wait":
            return "wait"
        if family == "rest":
            return "rest"
        if family == "dialogue":
            return "dialogue"
        return "action"

    @staticmethod
    def _bind_single_adjudication(
        adjudication: ActionAdjudication,
        *,
        player_input: PlayerInput,
        view: PlayerView,
    ) -> ActionAdjudication:
        return adjudication.model_copy(
            update={
                "request_id": player_input.client_action_id,
                "source_revision": view.revision,
                "actor_id": player_input.actor_id,
            },
            deep=True,
        )

    async def _single_keeper_capabilities(
        self,
        player_input: PlayerInput,
        view: PlayerView,
    ) -> KeeperCapabilityView | None:
        try:
            return await self._player_view_projector.keeper_capabilities(
                player_input,
                expected_revision=view.revision,
            )
        except (AttributeError, NotImplementedError):
            return None
