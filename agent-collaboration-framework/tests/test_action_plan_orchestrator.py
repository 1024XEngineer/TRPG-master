from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionPlan,
    ActionPlanPolicy,
    ActionPlanPolicyError,
    ActionPlanStep,
    ActionTarget,
    CancelActionPlanRequest,
    CheckDecisionRequest,
    ContractError,
    EnterLocationEffect,
    GetAdjudicationStatusRequest,
    ModuleContent,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerInput,
    RequiredAdjudicationCheck,
    SceneSpec,
    SelectCheckChoice,
    SingleActionDecision,
    SkillCheckCandidate,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
    SequenceDiceSource,
)
from collaboration_framework.host.adapters import InMemoryActionPlanRunStore
from collaboration_framework.host.application import (
    ActionPlanNarrationValidationError,
    ActionPlanNarrator,
    ActionPlanOrchestrator,
    HostTurnDecisionExecutor,
    HostTurnDecisionParser,
    PlayerViewProjector,
    TurnExecutionError,
)
from collaboration_framework.host.ports import (
    ActionPlanBusyError,
    ActionPlanVersionConflictError,
)

ROOT = Path(__file__).resolve().parents[1]


def load_model(path: str, model_type):
    return model_type.model_validate_json((ROOT / path).read_text(encoding="utf-8"))


def player_input(action_id: str = "parent-plan-1", utterance: str = "连续行动") -> PlayerInput:
    return PlayerInput(
        room_id="room_01",
        player_id="player_01",
        actor_id="pc_1",
        client_action_id=action_id,
        utterance=utterance,
    )


def plan(length: int) -> ActionPlan:
    kinds = ("travel", "action", "dialogue", "action", "action")
    return ActionPlan(
        goal=f"完成 {length} 个连续目标",
        steps=tuple(
            ActionPlanStep(
                kind=kinds[index % len(kinds)],
                semantic_goal=f"完成步骤 {index + 1}",
            )
            for index in range(length)
        ),
    )


class RecordingAdjudicator:
    def __init__(self, world_ref: str, *, check_step: int | None = None) -> None:
        self.world_ref = world_ref
        self.check_step = check_step
        self.contexts = []

    async def adjudicate(self, context):
        self.contexts.append(context)
        check = NoAdjudicationCheck()
        if context.step_index == self.check_step:
            check = RequiredAdjudicationCheck(
                candidates=(
                    SkillCheckCandidate(
                        candidate_id="spot",
                        skill_id="spot",
                        difficulty="regular",
                        method_summary="仔细观察",
                        player_safe_reason="侧重发现细节",
                    ),
                )
            )
        return ActionAdjudication(
            request_id="model-cannot-control-this",
            source_revision="model-cannot-control-this",
            actor_id="model-cannot-control-this",
            summary=context.step.semantic_goal,
            target=ActionTarget(kind="world", id=self.world_ref),
            method=ActionMethod(family=context.step.kind, description=context.step.semantic_goal),
            check=check,
            success_effects=(NarrativeOnlyEffect(),),
            failure_effects=(NarrativeOnlyEffect(),),
        )


class CanonTravelAdjudicator(RecordingAdjudicator):
    async def adjudicate(self, context):
        self.contexts.append(context)
        if context.step_index == 0:
            assert context.player_view.scene.id == "study"
            assert "cemetery" not in {
                entity.id for entity in context.player_view.scene.visible_entities
            }
            return ActionAdjudication(
                request_id="untrusted",
                source_revision="untrusted",
                actor_id="untrusted",
                summary="前往墓地",
                target=ActionTarget(kind="location", id="cemetery"),
                method=ActionMethod(family="travel", description="沿道路前往墓地"),
                check=NoAdjudicationCheck(),
                success_effects=(EnterLocationEffect(location_id="cemetery"),),
            )
        assert context.player_view.scene.id == "cemetery"
        assert "butler" in {entity.id for entity in context.player_view.scene.visible_entities}
        return ActionAdjudication(
            request_id="untrusted",
            source_revision="untrusted",
            actor_id="untrusted",
            summary="询问守墓人",
            target=ActionTarget(kind="entity", id="butler"),
            method=ActionMethod(family="dialogue", description="询问最近的异常"),
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )


class CrashAfterCommitExecutor:
    def __init__(self, service: AdjudicationEngineService) -> None:
        self.service = service
        self.crashed = False

    async def submit(self, request):
        execution = await self.service.submit(request)
        if not self.crashed:
            self.crashed = True
            raise RuntimeError("simulated process crash after Engine commit")
        return execution

    async def get_status(self, request):
        return await self.service.get_status(request)


class RevisionChangesBeforeFirstSubmitExecutor:
    def __init__(self, service: AdjudicationEngineService) -> None:
        self.service = service
        self.changed = False

    async def submit(self, request):
        if not self.changed:
            self.changed = True
            competing = request.adjudication.model_copy(
                update={"request_id": "competing-single-action"},
                deep=True,
            )
            await self.service.submit(
                SubmitAdjudicationRequest(
                    room_id=request.room_id,
                    player_id=request.player_id,
                    adjudication=competing,
                )
            )
        return await self.service.submit(request)

    async def get_status(self, request):
        return await self.service.get_status(request)


class ClarificationAdjudicator:
    async def adjudicate(self, context):
        raise TurnExecutionError(
            "STEP_AMBIGUOUS",
            "当前步骤目标不明确",
            retryable=False,
        )


class OutOfScopeNarrationModel:
    async def generate(self, context):
        return {
            "kind": "narration",
            "text": "你完成了已经结算的行动。",
            "claimed_evidence_refs": ["hidden-or-uncommitted-event"],
            "suggested_actions": [],
        }


def runtime(*, two_scenes: bool = False):
    module = load_model("fixtures/demo-module.json", ModuleContent)
    if two_scenes:
        cemetery = SceneSpec(
            id="cemetery",
            name="墓地",
            content="墓碑之间站着一位守墓人。",
            player_visible_name="墓地",
            player_visible_description="墓碑之间站着一位守墓人。",
            entity_ids=("butler",),
        )
        module = module.model_copy(
            update={"scenes": (*module.scenes, cemetery)},
            deep=True,
        )
    state = load_model("fixtures/demo-state.json", GameState)
    actor = state.actors["pc_1"]
    actor_state = dict(actor.state)
    actor_state.update({"skills": {"spot": 60}, "skill_labels": {"spot": "侦查"}})
    actors = dict(state.actors)
    actors["pc_1"] = actor.model_copy(update={"state": actor_state}, deep=True)
    state = state.model_copy(update={"actors": actors}, deep=True)
    engine_store = InMemoryEngineStore()
    engine_store.register_room(module_content=module, initial_state=state)
    view_projector = PlayerViewProjector(RuleEngineService(engine_store))
    return module, engine_store, view_projector


def orchestrator(
    *,
    action_plan_store=None,
    adjudicator=None,
    executor=None,
    policy=None,
    two_scenes: bool = False,
):
    module, engine_store, projector = runtime(two_scenes=two_scenes)
    adjudicator = adjudicator or RecordingAdjudicator(module.world_ref)
    service = executor or AdjudicationEngineService(engine_store)
    plan_store = action_plan_store or InMemoryActionPlanRunStore()
    return (
        ActionPlanOrchestrator(
            store=plan_store,
            adjudicator=adjudicator,
            executor=service,
            player_view_projector=projector,
            policy=policy,
            lease_seconds=1,
        ),
        adjudicator,
        service,
        plan_store,
        engine_store,
    )


@pytest.mark.asyncio
async def test_five_steps_cross_soft_window_without_becoming_product_limit() -> None:
    service, adjudicator, _, _, engine_store = orchestrator()
    original = player_input()

    first_window = await service.start_or_resume(
        original,
        plan=plan(5),
        worker_id="worker-1",
        auto_continue=False,
    )

    assert first_window.run.status == "checkpointed"
    assert first_window.run.current_step_index == 3
    assert [context.player_view.revision for context in adjudicator.contexts] == ["0", "1", "2"]

    completed_actions = await service.start_or_resume(
        original,
        plan=plan(5),
        worker_id="worker-2",
    )
    assert completed_actions.run.status == "awaiting_narration"
    assert completed_actions.run.current_step_index == 5
    assert [context.player_view.revision for context in adjudicator.contexts] == [
        "0",
        "1",
        "2",
        "3",
        "4",
    ]
    assert len(engine_store.inspect_domain_events("room_01")) == 5

    completed = await service.mark_narration_completed(
        room_id="room_01",
        parent_action_id=original.client_action_id,
    )
    assert completed.status == "completed"


def test_decision_parser_accepts_variable_lengths_and_rejects_invalid_shape() -> None:
    for length in (2, 3, 4, 5):
        parsed = HostTurnDecisionParser.parse(plan(length).to_json_dict())
        assert isinstance(parsed, ActionPlan)
        assert len(parsed.steps) == length

    one_step = {
        "kind": "action_plan",
        "goal": "只有一步",
        "steps": [{"kind": "action", "semantic_goal": "执行"}],
    }
    with pytest.raises(ContractError, match="结构校验"):
        HostTurnDecisionParser.parse(one_step)
    with pytest.raises(ActionPlanPolicyError) as raised:
        HostTurnDecisionParser.parse(
            plan(5).to_json_dict(),
            policy=ActionPlanPolicy(max_plan_steps=4, max_steps_per_advance=3),
        )
    assert raised.value.code == "PLAN_TOO_LARGE"


@pytest.mark.asyncio
async def test_plan_too_large_rejects_before_store_or_engine_write() -> None:
    service, _, _, store, engine_store = orchestrator(
        policy=ActionPlanPolicy(max_plan_steps=4, max_steps_per_advance=3)
    )
    original = player_input()

    with pytest.raises(ActionPlanPolicyError, match="超过当前技术上限") as raised:
        await service.start_or_resume(original, plan=plan(5))

    assert raised.value.code == "PLAN_TOO_LARGE"
    assert await store.load("room_01", original.client_action_id) is None
    assert engine_store.inspect_domain_events("room_01") == ()


@pytest.mark.asyncio
async def test_destination_step_is_adjudicated_only_after_travel_revision() -> None:
    module, engine_store, projector = runtime(two_scenes=True)
    adjudicator = CanonTravelAdjudicator(module.world_ref)
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=projector,
    )
    travel_plan = ActionPlan(
        goal="到墓地问守墓人",
        steps=(
            ActionPlanStep(kind="travel", semantic_goal="前往墓地"),
            ActionPlanStep(kind="dialogue", semantic_goal="询问守墓人"),
        ),
    )

    result = await service.start_or_resume(
        player_input(utterance="到墓地问守墓人"),
        plan=travel_plan,
    )

    assert result.run.status == "awaiting_narration"
    assert [context.player_view.scene.id for context in adjudicator.contexts] == [
        "study",
        "cemetery",
    ]
    assert adjudicator.contexts[1].player_view.revision == "2"


@pytest.mark.asyncio
async def test_pending_check_stops_plan_and_resumes_same_step_after_decision() -> None:
    module, engine_store, projector = runtime()
    adjudicator = RecordingAdjudicator(module.world_ref, check_step=0)
    engine = AdjudicationEngineService(
        engine_store,
        dice=DiceRoller(SequenceDiceSource([10])),
    )
    store = InMemoryActionPlanRunStore()
    service = ActionPlanOrchestrator(
        store=store,
        adjudicator=adjudicator,
        executor=engine,
        player_view_projector=projector,
    )
    original = player_input()

    waiting = await service.start_or_resume(original, plan=plan(2))
    assert waiting.run.status == "waiting_for_player"
    assert waiting.run.current_step_index == 0
    pending = waiting.latest_execution
    assert pending is not None and pending.pending_decision is not None

    resolved = await engine.decide(
        CheckDecisionRequest(
            request_id="choose-plan-step-1",
            room_id="room_01",
            player_id="player_01",
            source_revision=pending.view_revision,
            decision_id=pending.pending_decision.decision_id,
            decision_version=pending.pending_decision.decision_version,
            choice=SelectCheckChoice(candidate_id="spot"),
        )
    )
    assert resolved.status == "resolved"

    resumed = await service.start_or_resume(original, plan=plan(2))
    assert resumed.run.status == "awaiting_narration"
    assert resumed.run.current_step_index == 2
    assert [context.step_index for context in adjudicator.contexts] == [0, 1]
    status = await engine.get_status(
        GetAdjudicationStatusRequest(
            room_id="room_01",
            player_id="player_01",
            action_request_id=waiting.run.steps[0].step_request_id,
        )
    )
    assert status.status == "resolved"


@pytest.mark.asyncio
async def test_engine_commit_before_plan_cursor_update_reconciles_without_replay() -> None:
    module, engine_store, projector = runtime()
    engine = AdjudicationEngineService(engine_store)
    crashing = CrashAfterCommitExecutor(engine)
    store = InMemoryActionPlanRunStore()
    adjudicator = RecordingAdjudicator(module.world_ref)
    service = ActionPlanOrchestrator(
        store=store,
        adjudicator=adjudicator,
        executor=crashing,
        player_view_projector=projector,
        lease_seconds=1,
    )
    original = player_input()

    with pytest.raises(RuntimeError, match="simulated process crash"):
        await service.start_or_resume(
            original,
            plan=plan(2),
            worker_id="crashed-worker",
        )
    stranded = await store.load("room_01", original.client_action_id)
    assert stranded is not None
    assert stranded.steps[0].status == "ready"
    assert len(engine_store.inspect_domain_events("room_01")) == 1

    future = datetime.now(UTC) + timedelta(seconds=2)
    await store.claim(
        room_id="room_01",
        parent_action_id=original.client_action_id,
        worker_id="recovery-worker",
        now=future,
        lease_expires_at=future + timedelta(seconds=1),
    )
    recovered = await service.start_or_resume(
        original,
        plan=plan(2),
        worker_id="recovery-worker",
    )

    assert recovered.run.status == "awaiting_narration"
    assert len(engine_store.inspect_domain_events("room_01")) == 2
    assert [context.step_index for context in adjudicator.contexts] == [0, 1]


@pytest.mark.asyncio
async def test_unsubmitted_stale_step_is_refreshed_on_same_parent_retry() -> None:
    module, engine_store, projector = runtime()
    engine = AdjudicationEngineService(engine_store)
    executor = RevisionChangesBeforeFirstSubmitExecutor(engine)
    adjudicator = RecordingAdjudicator(module.world_ref)
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=executor,
        player_view_projector=projector,
    )
    original = player_input()

    stale = await service.start_or_resume(original, plan=plan(2))
    assert stale.run.status == "retryable_failure"
    assert stale.run.current_step_index == 0
    assert stale.run.steps[0].status == "pending"
    assert stale.run.steps[0].safe_failure_code == "STEP_REVISION_CHANGED"

    resumed = await service.start_or_resume(original, plan=plan(2))

    assert resumed.run.status == "awaiting_narration"
    assert [context.player_view.revision for context in adjudicator.contexts] == [
        "0",
        "1",
        "2",
    ]
    assert len(engine_store.inspect_domain_events("room_01")) == 3


@pytest.mark.asyncio
async def test_room_reservation_blocks_other_parent_until_plan_is_terminal() -> None:
    service, _, _, store, _ = orchestrator()
    first = player_input("first-parent")
    await service.start_or_resume(
        first,
        plan=plan(4),
        worker_id="worker-1",
        auto_continue=False,
    )

    second_service, _, _, _, _ = orchestrator(action_plan_store=store)
    with pytest.raises(ActionPlanBusyError) as raised:
        await second_service.start_or_resume(
            player_input("second-parent", "另一个行动"),
            plan=plan(2),
        )
    assert raised.value.code == "ACTION_IN_PROGRESS"


@pytest.mark.asyncio
async def test_single_action_fast_path_creates_no_plan_run() -> None:
    service, _, engine, store, engine_store = orchestrator()
    original = player_input("single-action", "观察四周")
    decision = SingleActionDecision(
        adjudication=ActionAdjudication(
            request_id="untrusted",
            source_revision="untrusted",
            actor_id="untrusted",
            summary="观察四周",
            target=ActionTarget(kind="world", id="coc-7e"),
            method=ActionMethod(family="observe", description="观察四周"),
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )
    )
    dispatcher = HostTurnDecisionExecutor(
        plan_orchestrator=service,
        executor=engine,
        player_view_projector=PlayerViewProjector(RuleEngineService(engine_store)),
    )

    result = await dispatcher.execute(original, decision)

    assert result.execution.status == "resolved"
    assert result.execution.action_request_id == original.client_action_id
    assert await store.load("room_01", original.client_action_id) is None
    assert len(engine_store.inspect_domain_events("room_01")) == 1


@pytest.mark.asyncio
async def test_parent_id_reuse_with_different_input_fails_closed() -> None:
    service, _, _, _, _ = orchestrator()
    await service.start_or_resume(
        player_input(utterance="原始计划"),
        plan=plan(4),
        worker_id="worker-1",
        auto_continue=False,
    )

    with pytest.raises(ActionPlanPolicyError) as raised:
        await service.start_or_resume(
            player_input(utterance="篡改后的计划"),
            plan=plan(4),
        )
    assert raised.value.code == "PARENT_ACTION_CONFLICT"


@pytest.mark.asyncio
async def test_in_memory_plan_store_cas_allows_only_one_worker_update() -> None:
    service, _, _, store, _ = orchestrator()
    original = player_input()
    checkpointed = await service.start_or_resume(
        original,
        plan=plan(4),
        worker_id="worker-1",
        auto_continue=False,
    )
    base = checkpointed.run
    first = base.model_copy(
        update={
            "run_version": base.run_version + 1,
            "updated_at": datetime.now(UTC),
        },
        deep=True,
    )
    await store.compare_and_swap(
        expected_run_version=base.run_version,
        updated_run=first,
    )

    with pytest.raises(ActionPlanVersionConflictError):
        await store.compare_and_swap(
            expected_run_version=base.run_version,
            updated_run=first,
        )


@pytest.mark.asyncio
async def test_cancel_remaining_is_idempotent_at_checkpoint_boundary() -> None:
    service, _, _, _, _ = orchestrator()
    original = player_input()
    checkpointed = await service.start_or_resume(
        original,
        plan=plan(4),
        worker_id="worker-1",
        auto_continue=False,
    )
    assert checkpointed.run.current_step_index == 3
    request = CancelActionPlanRequest(
        request_id="cancel-plan-1",
        room_id="room_01",
        player_id="player_01",
        actor_id="pc_1",
        parent_action_id=original.client_action_id,
    )

    cancelled = await service.cancel_remaining(request)
    replay = await service.cancel_remaining(request)

    assert cancelled.status == "cancelled"
    assert replay == cancelled
    assert cancelled.completed_steps == 3


@pytest.mark.asyncio
async def test_needs_clarification_can_be_cancelled_without_running_later_steps() -> None:
    service, _, _, _, engine_store = orchestrator(adjudicator=ClarificationAdjudicator())
    original = player_input()

    paused = await service.start_or_resume(original, plan=plan(2))
    assert paused.run.status == "needs_clarification"
    assert paused.run.current_step_index == 0
    assert [step.status for step in paused.run.steps] == ["stopped", "pending"]

    cancelled = await service.cancel_remaining(
        CancelActionPlanRequest(
            request_id="cancel-ambiguous-plan",
            room_id="room_01",
            player_id="player_01",
            actor_id="pc_1",
            parent_action_id=original.client_action_id,
        )
    )

    assert cancelled.status == "cancelled"
    assert engine_store.inspect_domain_events("room_01") == ()


@pytest.mark.asyncio
async def test_progress_delivery_failure_does_not_change_authoritative_execution() -> None:
    service, _, _, _, engine_store = orchestrator()

    async def unavailable_progress_sink(event) -> None:
        raise RuntimeError("progress transport unavailable")

    result = await service.start_or_resume(
        player_input(),
        plan=plan(2),
        on_progress=unavailable_progress_sink,
    )

    assert result.run.status == "awaiting_narration"
    assert result.run.completed_steps == 2
    assert len(engine_store.inspect_domain_events("room_01")) == 2


@pytest.mark.asyncio
async def test_narrator_rejects_evidence_outside_committed_public_refs() -> None:
    service, _, _, _, _ = orchestrator()
    original = player_input()
    await service.start_or_resume(original, plan=plan(2))
    context = await service.build_narration_context(original)

    assert context.allowed_evidence_refs
    with pytest.raises(ActionPlanNarrationValidationError) as raised:
        await ActionPlanNarrator(OutOfScopeNarrationModel()).narrate(context)

    assert raised.value.reason == "evidence_scope"
