from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from collaboration_framework.contracts import (
    ActionPlanPolicy,
    NarrationEvidence,
    PlayerInput,
    PostRollDecisionRequest,
)
from collaboration_framework.host.application import (
    ActionPlanNarrationValidationError,
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


class _NarrationContextStub:
    def __init__(self, evidence: NarrationEvidence, termination_status: str) -> None:
        self.narration_evidence = (evidence,)
        self.termination_status = termination_status
        self.narration_retry_hint: str | None = None
        self.player_input = SimpleNamespace(
            client_action_id="action-narration-test",
            utterance="",
        )
        self.player_view = SimpleNamespace(
            scene=SimpleNamespace(visible_entities=()),
        )
        self.completed_steps: tuple[object, ...] = ()

    def model_copy(self, *, update: dict[str, object]):
        copied = _NarrationContextStub(
            self.narration_evidence[0],
            self.termination_status,
        )
        copied.narration_retry_hint = cast(str | None, update["narration_retry_hint"])
        return copied


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


@pytest.mark.parametrize(
    ("outcomes", "termination_status", "expected"),
    (
        (
            ("failure",),
            "resolved",
            "这次行动未能成功，局面没有产生当前可确认的新结果。",
        ),
        (
            ("success", "failure"),
            "stopped",
            "当前步骤未能成功；此前已经完成的步骤仍然保留。",
        ),
        (("cancelled",), "cancelled", "这次行动已经取消。"),
        (("success",), "resolved", "这次行动已经按当前可确认的结果完成。"),
    ),
)
def test_deterministic_narration_fallback_preserves_action_outcome(
    outcomes: tuple[str, ...],
    termination_status: str,
    expected: str,
) -> None:
    """模型叙事被拒绝后，兜底文案仍必须忠实表达权威行动结果。"""

    context = SimpleNamespace(
        termination_status=termination_status,
        player_input=SimpleNamespace(client_action_id="action-fallback"),
        completed_steps=tuple(
            SimpleNamespace(outcome=outcome, committed_results=()) for outcome in outcomes
        ),
        player_view=SimpleNamespace(
            scene=SimpleNamespace(visible_entities=()),
        ),
    )

    output = ActionPlanTurnApplication._deterministic_narration_fallback(cast(Any, context))

    assert output.text == expected


def test_clarification_fallback_points_to_visible_dead_body() -> None:
    """模型连续忽略可见尸体时，兜底应给出权威位置而不是继续要求寻找。"""

    context = SimpleNamespace(
        termination_status="needs_clarification",
        player_input=SimpleNamespace(
            client_action_id="find-body",
            utterance="去找他的尸体",
        ),
        completed_steps=(),
        player_view=SimpleNamespace(
            scene=SimpleNamespace(
                visible_entities=(
                    SimpleNamespace(
                        name="梅洛迪亚斯·杰弗逊",
                        observable_state=(SimpleNamespace(key="consciousness", value="dead"),),
                    ),
                ),
            ),
        ),
    )

    output = ActionPlanTurnApplication._deterministic_narration_fallback(cast(Any, context))

    assert output.kind == "clarification"
    assert output.text.startswith("梅洛迪亚斯·杰弗逊的尸体就在当前场景中")


def test_unresolved_travel_fallback_narrates_not_found_without_substitution() -> None:
    """无法创建的明确地点应说没找到，不应返回通用表单式澄清。"""

    context = SimpleNamespace(
        termination_status="needs_clarification",
        player_input=SimpleNamespace(
            client_action_id="unresolved-clinic",
            utterance="去一个与当前背景冲突的诊所",
        ),
        completed_steps=(),
        player_view=SimpleNamespace(scene=SimpleNamespace(visible_entities=())),
    )

    output = ActionPlanTurnApplication._deterministic_narration_fallback(cast(Any, context))

    assert "没有" in output.text
    assert "找到" in output.text
    assert "仍停留在原处" in output.text
    assert "作用于谁或什么" not in output.text
    assert "具体变化" not in output.text


def test_partial_travel_success_fallback_keeps_the_arrival() -> None:
    """旅行已提交、后续步骤失败时，保底叙事不能把玩家送回原处。"""

    context = SimpleNamespace(
        termination_status="needs_clarification",
        player_input=SimpleNamespace(
            client_action_id="partial-inn",
            utterance="去旅馆，开一间房休息",
        ),
        completed_steps=(
            SimpleNamespace(
                outcome="success",
                semantic_goal="前往旅馆",
                committed_results=(),
            ),
        ),
        player_view=SimpleNamespace(
            scene=SimpleNamespace(
                name="镇上的旅店",
                visible_entities=(),
            ),
        ),
    )

    output = ActionPlanTurnApplication._deterministic_narration_fallback(cast(Any, context))

    assert output.kind == "clarification"
    assert "已经抵达镇上的旅店" in output.text
    assert "后续行动" in output.text
    assert "没有" not in output.text
    assert "仍停留在原处" not in output.text


def test_planning_failure_returns_host_reply_without_execution() -> None:
    """规划结构连续失败时必须有主持人回复，并保持零权威写入。"""

    player_input = PlayerInput(
        room_id="room-315",
        player_id="player-315",
        actor_id="actor-315",
        client_action_id="76664d06-3ac2-411b-8986-1ff12ed53cbf",
        utterance="去墓地",
    )
    result = ActionPlanTurnApplication._planning_failure_clarification(
        player_input=player_input,
        player_view=cast(Any, SimpleNamespace()),
    )

    assert result.status == "needs_clarification"
    assert result.execution is None
    assert result.narration is not None
    assert result.narration.kind == "clarification"
    assert "行动的对象或地点" in result.narration.text


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
        _NarrationContextStub(evidence, "resolved"),
    )

    narration = await application._narrate(context)

    assert narrate.await_count == 2
    retry_context = narrate.await_args_list[1].args[0]
    assert "石板下的地穴入口" in retry_context.narration_retry_hint
    assert "claim" in retry_context.narration_retry_hint
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
        _NarrationContextStub(evidence, "needs_clarification"),
    )

    narration = await application._narrate(context)

    assert narration.kind == "clarification"
    assert evidence.subject_name not in narration.text
    assert narration.claimed_evidence_refs == ()
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
