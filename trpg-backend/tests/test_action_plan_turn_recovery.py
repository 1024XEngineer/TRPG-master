from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from collaboration_framework.contracts import (
    ActionPlanPolicy,
    NarrationEvidence,
    PostRollDecisionRequest,
)
from collaboration_framework.host.application import (
    ActionPlanNarrationValidationError,
    TurnExecutionError,
)
from collaboration_framework.host.schemas import ActionPlanNarrationContext

from app.core.action_plan_turn import ActionPlanTurnApplication


def _run(*, cancel_id: str | None) -> SimpleNamespace:
    return SimpleNamespace(
        room_id="room-281",
        player_id="player-281",
        actor_id="actor-281",
        parent_action_id="plan-281",
        parent_utterance="完成连续行动",
        plan=SimpleNamespace(goal="完成连续行动"),
        plan_id="plan-281",
        status="waiting_for_player",
        current_step_index=0,
        pending_cancel_request_id=cancel_id,
        steps=(
            SimpleNamespace(
                step_request_id="step-281",
                status="waiting_for_player",
                adjudication_execution=None,
            ),
        ),
    )


def _status(status: str) -> SimpleNamespace:
    check_run = SimpleNamespace(
        check_id="check-281",
        version=1,
        post_roll_options=(SimpleNamespace(kind="accept_result", option_id="accept-current"),),
    )
    execution = SimpleNamespace(
        status=status,
        view_revision="revision-7",
        check_run=check_run if status == "awaiting_post_roll_decision" else None,
    )
    return SimpleNamespace(status=status, execution=execution)


class _Engine:
    def __init__(self, status: SimpleNamespace) -> None:
        self.status = status
        self.status_requests = []
        self.post_roll_requests: list[PostRollDecisionRequest] = []

    async def get_status(self, request):
        self.status_requests.append(request)
        return self.status

    async def decide_post_roll(self, request: PostRollDecisionRequest):
        self.post_roll_requests.append(request)
        self.status = _status("resolved")
        return self.status.execution


class _Orchestrator:
    def __init__(self, run: SimpleNamespace) -> None:
        self.run = run
        self.resume_calls = []
        self.adjudicator = object()
        self.policy = ActionPlanPolicy(max_repair_attempts=3)

    async def get_run(self, room_id: str, parent_action_id: str):
        assert room_id == self.run.room_id
        assert parent_action_id == self.run.parent_action_id
        return self.run

    async def resume_owned(self, **kwargs):
        self.resume_calls.append(kwargs)
        return SimpleNamespace(run=self.run)


def _application(run: SimpleNamespace, engine: _Engine, orchestrator: _Orchestrator):
    application = object.__new__(ActionPlanTurnApplication)
    application._adjudication_engine = engine
    application._orchestrator = orchestrator
    application._resolve_actor_id = AsyncMock(return_value=run.actor_id)
    application._finish_plan_with_phases = AsyncMock(return_value="recovered")
    return application


def test_application_injects_plan_repair_dependencies_into_single_action_path() -> None:
    run = _run(cancel_id=None)
    engine = _Engine(_status("resolved"))
    orchestrator = _Orchestrator(run)

    application = ActionPlanTurnApplication(
        store=cast(Any, object()),
        engine=cast(Any, object()),
        adjudication_engine=cast(Any, engine),
        planner=cast(Any, object()),
        orchestrator=cast(Any, orchestrator),
        narrator=cast(Any, object()),
        recent_history_source=cast(Any, object()),
        recent_history_budget=cast(Any, object()),
        recent_history_enabled=False,
    )

    assert application._dispatcher._repair_adjudicator is orchestrator.adjudicator
    assert application._dispatcher._policy is orchestrator.policy


@pytest.mark.asyncio
async def test_narration_falls_back_to_required_player_safe_evidence() -> None:
    application = object.__new__(ActionPlanTurnApplication)
    narrate = AsyncMock(side_effect=ActionPlanNarrationValidationError("required_evidence_missing"))
    application._narrator = SimpleNamespace(narrate=narrate)
    evidence = NarrationEvidence(
        ref="evt-crypt-discovered",
        kind="entity_discovered",
        subject_id="crypt_entrance",
        subject_name="石板下的地穴入口",
        description="一块沉重石板遮住了向下的通道。",
        required_in_narration=True,
    )
    context = cast(
        ActionPlanNarrationContext,
        SimpleNamespace(
            narration_evidence=(evidence,),
            termination_status="resolved",
        ),
    )

    narration = await application._narrate(context)

    assert narrate.await_count == 2
    assert narration.claimed_evidence_refs == (evidence.ref,)
    assert "石板下的地穴入口" in narration.text
    assert "沉重石板" in narration.text
    assert "。。" not in narration.text


@pytest.mark.asyncio
async def test_required_evidence_fallback_never_changes_clarification_scope() -> None:
    application = object.__new__(ActionPlanTurnApplication)
    narrate = AsyncMock(side_effect=ActionPlanNarrationValidationError("required_evidence_missing"))
    application._narrator = SimpleNamespace(narrate=narrate)
    evidence = NarrationEvidence(
        ref="evt-crypt-discovered",
        kind="entity_discovered",
        subject_id="crypt_entrance",
        subject_name="石板下的地穴入口",
        required_in_narration=True,
    )
    context = cast(
        ActionPlanNarrationContext,
        SimpleNamespace(
            narration_evidence=(evidence,),
            termination_status="needs_clarification",
        ),
    )

    with pytest.raises(TurnExecutionError) as raised:
        await application._narrate(context)

    assert raised.value.code == "PLAN_NARRATION_INVALID"
    assert narrate.await_count == 2


@pytest.mark.asyncio
async def test_resume_owned_recovers_intent_after_crash_before_engine_write() -> None:
    run = _run(cancel_id="cancel-original")
    engine = _Engine(_status("awaiting_post_roll_decision"))
    orchestrator = _Orchestrator(run)
    application = _application(run, engine, orchestrator)

    result = await application.resume_owned(
        room_id=run.room_id,
        player_id=run.player_id,
        parent_action_id=run.parent_action_id,
    )

    assert result == "recovered"
    assert len(engine.post_roll_requests) == 1
    request = engine.post_roll_requests[0]
    assert request.request_id == "cancel-original:accept-current"
    assert request.source_revision == "revision-7"
    assert request.check_id == "check-281"
    assert len(orchestrator.resume_calls) == 1


@pytest.mark.asyncio
async def test_cancel_retry_reconciles_resolved_engine_after_crash_before_plan_write() -> None:
    run = _run(cancel_id="cancel-original")
    engine = _Engine(_status("resolved"))
    orchestrator = _Orchestrator(run)
    application = _application(run, engine, orchestrator)

    result = await application.cancel_remaining(
        room_id=run.room_id,
        player_id=run.player_id,
        parent_action_id=run.parent_action_id,
        request_id="cancel-retry-with-new-id",
    )

    assert result == "recovered"
    assert engine.post_roll_requests == []
    assert len(orchestrator.resume_calls) == 1
    assert orchestrator.resume_calls[0]["parent_action_id"] == run.parent_action_id
