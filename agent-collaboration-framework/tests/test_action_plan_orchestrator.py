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
    AdjudicationValidationError,
    AdvanceWorldTimeEffect,
    CancelActionPlanRequest,
    CheckDecisionRequest,
    ChangeEntityStateEffect,
    ContractError,
    EnterLocationEffect,
    GetAdjudicationStatusRequest,
    ModuleContent,
    ModuleContentV3,
    NarrationEvidence,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerInput,
    PostRollDecisionRequest,
    PushAdjudication,
    Repairability,
    RequiredAdjudicationCheck,
    SceneSpec,
    SelectCheckChoice,
    SingleActionDecision,
    SkillCheckCandidate,
    SubmitAdjudicationRequest,
    ValidationResult,
)
from collaboration_framework.engine import (
    ActorState,
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
from collaboration_framework.host.application.action_plan_orchestrator import (
    _REPAIR_HINTS,
)
from collaboration_framework.host.ports import (
    ActionPlanBusyError,
    ActionPlanStepFailure,
    ActionPlanVersionConflictError,
)
from collaboration_framework.host.schemas import (
    ActionPlanRun,
    ActionPlanStepContext,
    ActionPlanStepRun,
    SingleActionClarificationResult,
    SingleActionTurnResult,
)

ROOT = Path(__file__).resolve().parents[1]


def load_model(path: str, model_type):
    return model_type.model_validate_json((ROOT / path).read_text(encoding="utf-8"))


def player_input(
    action_id: str = "parent-plan-1", utterance: str = "连续行动"
) -> PlayerInput:
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
            method=ActionMethod(
                family=context.step.kind, description=context.step.semantic_goal
            ),
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
        assert "butler" in {
            entity.id for entity in context.player_view.scene.visible_entities
        }
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


class FailSecondStepOnceAdjudicator(RecordingAdjudicator):
    def __init__(self, world_ref: str) -> None:
        super().__init__(world_ref)
        self.failed = False

    async def adjudicate(self, context):
        if context.step_index == 1 and not self.failed:
            self.contexts.append(context)
            self.failed = True
            raise RuntimeError("temporary provider outage")
        return await super().adjudicate(context)


class ClassifiedSecondStepAdjudicator(RecordingAdjudicator):
    async def adjudicate(self, context):
        if context.step_index == 1:
            self.contexts.append(context)
            provider_error = RuntimeError("provider timed out")
            raise TurnExecutionError(
                "MODEL_UPSTREAM_UNAVAILABLE",
                "主持模型暂时不可用，当前步骤未生效，请重试",
                retryable=True,
            ) from provider_error
        return await super().adjudicate(context)


class RecordingStepFailureObserver:
    """收集进程内诊断，确认它不会混进 PlanRun 持久化结构。"""

    def __init__(self) -> None:
        self.failures: list[ActionPlanStepFailure] = []

    async def __call__(self, failure: ActionPlanStepFailure) -> None:
        self.failures.append(failure)


class RaisingStepFailureObserver:
    async def __call__(self, failure: ActionPlanStepFailure) -> None:
        raise RuntimeError("diagnostic sink unavailable")


class RejectSecondStepAdjudicator(RecordingAdjudicator):
    async def adjudicate(self, context):
        if context.step_index == 1:
            self.contexts.append(context)
            raise ContractError("provider output failed schema validation")
        return await super().adjudicate(context)


class MissingTargetAdjudicator(RecordingAdjudicator):
    """First proposal for step 2 references a target the Engine cannot resolve.

    A uniquely identifiable target with the wrong kind is now normalized by the
    Engine. A genuinely absent id still exercises the Host repair loop without
    overlapping that deterministic normalization responsibility.
    """

    def __init__(self, world_ref: str, *, repairs: bool = True) -> None:
        super().__init__(world_ref)
        self.repairs = repairs

    async def adjudicate(self, context):
        repaired = self.repairs and context.previous_rejection is not None
        if context.step_index != 1:
            return await super().adjudicate(context)
        if repaired:
            self.contexts.append(context)
            return ActionAdjudication(
                request_id="untrusted",
                source_revision="untrusted",
                actor_id="untrusted",
                summary="调查书架",
                target=ActionTarget(kind="entity", id="bookshelf"),
                method=ActionMethod(family="action", description="调查书架"),
                check=NoAdjudicationCheck(),
                success_effects=(NarrativeOnlyEffect(),),
            )
        self.contexts.append(context)
        return ActionAdjudication(
            request_id="untrusted",
            source_revision="untrusted",
            actor_id="untrusted",
            summary="调查书架",
            target=ActionTarget(kind="entity", id="missing-bookshelf"),
            method=ActionMethod(family="action", description="调查书架"),
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )


class SemanticallyDriftingRepairAdjudicator(MissingTargetAdjudicator):
    async def adjudicate(self, context):
        if context.step_index == 1 and context.previous_rejection is not None:
            self.contexts.append(context)
            return ActionAdjudication(
                request_id="untrusted",
                source_revision="untrusted",
                actor_id="untrusted",
                summary=context.step.semantic_goal,
                target=ActionTarget(kind="entity", id="butler"),
                method=ActionMethod(family="combat", description="攻击管家"),
                check=NoAdjudicationCheck(),
                success_effects=(NarrativeOnlyEffect(),),
            )
        return await super().adjudicate(context)


class VisibleTargetRepairAdjudicator(RecordingAdjudicator):
    async def adjudicate(self, context):
        if context.previous_rejection is not None:
            self.contexts.append(context)
            return ActionAdjudication(
                request_id="untrusted",
                source_revision="untrusted",
                actor_id="untrusted",
                summary=context.step.semantic_goal,
                target=ActionTarget(kind="entity", id="bookshelf"),
                method=ActionMethod(
                    family="observe", description=context.step.semantic_goal
                ),
                check=NoAdjudicationCheck(),
                success_effects=(NarrativeOnlyEffect(),),
            )
        return await super().adjudicate(context)


class ValidationRejectingExecutor:
    def __init__(
        self,
        service: AdjudicationEngineService,
        *,
        repairability: Repairability,
        rejected_summary: str | None = None,
    ) -> None:
        self.service = service
        self.repairability = repairability
        self.rejected_summary = rejected_summary
        self.submit_calls = []

    async def submit(self, request):
        self.submit_calls.append(request)
        if (
            self.rejected_summary is None
            or request.adjudication.summary == self.rejected_summary
        ):
            raise AdjudicationValidationError(
                ValidationResult(
                    status="rejected",
                    code="TEST_VALIDATION_REJECTION",
                    repairability=self.repairability,
                    fault="agent",
                    player_safe_reason="这次行动需要停下确认",
                    internal_reason="keeper-only hidden target evidence",
                    classification_coverage="partial_validation_failure",
                )
            )
        return await self.service.submit(request)

    async def get_status(self, request):
        return await self.service.get_status(request)


class ContractRejectingExecutor:
    def __init__(self, service: AdjudicationEngineService) -> None:
        self.service = service
        self.submit_calls = []

    async def submit(self, request):
        self.submit_calls.append(request)
        if request.adjudication.summary == "完成步骤 2":
            raise ContractError("ordinary contract failure")
        return await self.service.submit(request)

    async def get_status(self, request):
        return await self.service.get_status(request)


class AlwaysMissingTargetAdjudicator(RecordingAdjudicator):
    async def adjudicate(self, context):
        self.contexts.append(context)
        return ActionAdjudication(
            request_id="untrusted",
            source_revision="untrusted",
            actor_id="untrusted",
            summary=context.step.semantic_goal,
            target=ActionTarget(kind="world", id="missing-target"),
            method=ActionMethod(
                family="action", description=context.step.semantic_goal
            ),
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )


class PersistentRepairAdjudicator(RecordingAdjudicator):
    """首次不给持久效果，收到 Engine 反馈后补齐昏迷效果。"""

    async def adjudicate(self, context):
        self.contexts.append(context)
        if context.previous_rejection is None:
            return ActionAdjudication(
                request_id="untrusted",
                source_revision="untrusted",
                actor_id="untrusted",
                summary="击晕守墓人",
                target=ActionTarget(kind="entity", id="butler"),
                method=ActionMethod(family="knock_out", description="用撬棍砸晕他"),
                persistence_intent="character_state",
                check=NoAdjudicationCheck(),
            )
        return ActionAdjudication(
            request_id="untrusted",
            source_revision="untrusted",
            actor_id="untrusted",
            summary="击晕守墓人",
            target=ActionTarget(kind="entity", id="butler"),
            method=ActionMethod(family="knock_out", description="用撬棍砸晕他"),
            persistence_intent="character_state",
            check=NoAdjudicationCheck(),
            success_effects=(
                ChangeEntityStateEffect(
                    entity_id="butler",
                    key="consciousness",
                    value="unconscious",
                ),
            ),
        )


class PersistentEmptyAdjudicator(PersistentRepairAdjudicator):
    async def adjudicate(self, context):
        self.contexts.append(context)
        return ActionAdjudication(
            request_id="untrusted",
            source_revision="untrusted",
            actor_id="untrusted",
            summary="击晕守墓人",
            target=ActionTarget(kind="entity", id="butler"),
            method=ActionMethod(family="knock_out", description="用撬棍砸晕他"),
            persistence_intent="character_state",
            check=NoAdjudicationCheck(),
        )


class OutOfScopeNarrationModel:
    async def generate(self, context):
        return {
            "kind": "narration",
            "text": "你完成了已经结算的行动。",
            "claimed_evidence_refs": ["hidden-or-uncommitted-event"],
            "suggested_actions": [],
        }


class FirstPersonNarrationModel:
    async def generate(self, context):
        return {
            "kind": "narration",
            "text": "我带着你们进入墓园。",
            "claimed_evidence_refs": [],
            "suggested_actions": [],
        }


class MissingRequiredEvidenceNarrationModel:
    async def generate(self, context):
        return {
            "kind": "narration",
            "text": "你在墓碑附近发现了一些痕迹。",
            "claimed_evidence_refs": [],
            "suggested_actions": [],
        }


class ClaimsButOmitsRequiredEvidenceNarrationModel:
    async def generate(self, context):
        return {
            "kind": "narration",
            "text": "你在墓碑附近发现了一些痕迹。",
            "claimed_evidence_refs": [context.narration_evidence[0].ref],
            "suggested_actions": [],
        }


class AliasRequiredEvidenceNarrationModel:
    async def generate(self, context):
        return {
            "kind": "narration",
            "text": "沿着断续的痕迹，你确认这里藏着一个地穴入口。",
            "claimed_evidence_refs": [],
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
    on_step_failure=None,
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
            on_step_failure=on_step_failure,
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
    assert [context.player_view.revision for context in adjudicator.contexts] == [
        "0",
        "1",
        "2",
    ]

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


@pytest.mark.asyncio
async def test_persisted_narration_recovery_finishes_plan_without_replaying_engine_steps() -> (
    None
):
    service, _, _, _, engine_store = orchestrator()
    original = player_input("narration-recovery-parent")

    settled = await service.start_or_resume(original, plan=plan(2))
    assert settled.run.status == "awaiting_narration"
    context = await service.build_narration_context(original)
    assert context.allowed_evidence_refs
    assert len(engine_store.inspect_domain_events("room_01")) == 2

    recovered = await service.start_or_resume(original, plan=plan(2))
    assert recovered.run.status == "awaiting_narration"
    assert recovered.run.run_version == settled.run.run_version
    assert len(engine_store.inspect_domain_events("room_01")) == 2

    completed = await service.mark_narration_completed(
        room_id="room_01",
        parent_action_id=original.client_action_id,
    )
    replay = await service.mark_narration_completed(
        room_id="room_01",
        parent_action_id=original.client_action_id,
    )
    assert completed.status == "completed"
    assert replay == completed


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
    assert resolved.status == "awaiting_post_roll_decision"
    assert resolved.check_run is not None
    resolved = await engine.decide_post_roll(
        PostRollDecisionRequest(
            request_id="accept-plan-step-1",
            room_id="room_01",
            player_id="player_01",
            source_revision=resolved.view_revision,
            check_id=resolved.check_run.check_id,
            check_version=resolved.check_run.version,
            option_id="accept-current",
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


@pytest.mark.parametrize(
    ("roll_value", "expected_outcome", "expected_status"),
    ((10, "success", "cancelled"), (80, "failure", "stopped")),
)
@pytest.mark.asyncio
async def test_post_roll_cancel_accepts_current_roll_and_stops_remaining_steps(
    roll_value: int,
    expected_outcome: str,
    expected_status: str,
) -> None:
    module, engine_store, projector = runtime()
    adjudicator = RecordingAdjudicator(module.world_ref, check_step=0)
    engine = AdjudicationEngineService(
        engine_store,
        dice=DiceRoller(SequenceDiceSource([roll_value])),
    )
    plan_store = InMemoryActionPlanRunStore()
    service = ActionPlanOrchestrator(
        store=plan_store,
        adjudicator=adjudicator,
        executor=engine,
        player_view_projector=projector,
    )
    original = player_input("post-roll-cancel-parent")

    waiting = await service.start_or_resume(original, plan=plan(3))
    pending = waiting.latest_execution
    assert pending is not None and pending.pending_decision is not None
    rolled = await engine.decide(
        CheckDecisionRequest(
            request_id="post-roll-cancel-parent:select",
            room_id="room_01",
            player_id="player_01",
            source_revision=pending.view_revision,
            decision_id=pending.pending_decision.decision_id,
            decision_version=pending.pending_decision.decision_version,
            choice=SelectCheckChoice(candidate_id="spot"),
        )
    )
    assert rolled.status == "awaiting_post_roll_decision"
    assert rolled.check_run is not None

    cancel = CancelActionPlanRequest(
        request_id="post-roll-cancel-parent:cancel",
        room_id="room_01",
        player_id="player_01",
        actor_id="pc_1",
        parent_action_id=original.client_action_id,
    )
    intent = await service.request_cancel_after_current(cancel)
    assert intent.pending_cancel_request_id == cancel.request_id
    assert intent.status == "waiting_for_player"
    assert await service.request_cancel_after_current(cancel) == intent

    accepted = await engine.decide_post_roll(
        PostRollDecisionRequest(
            request_id=f"{cancel.request_id}:accept-current",
            room_id="room_01",
            player_id="player_01",
            source_revision=rolled.view_revision,
            check_id=rolled.check_run.check_id,
            check_version=rolled.check_run.version,
            option_id="accept-current",
        )
    )
    replay = await engine.decide_post_roll(
        PostRollDecisionRequest(
            request_id=f"{cancel.request_id}:accept-current",
            room_id="room_01",
            player_id="player_01",
            source_revision=rolled.view_revision,
            check_id=rolled.check_run.check_id,
            check_version=rolled.check_run.version,
            option_id="accept-current",
        )
    )
    assert accepted == replay
    assert accepted.outcome == expected_outcome

    stopped = await service.resume_owned(
        room_id="room_01",
        player_id="player_01",
        actor_id="pc_1",
        parent_action_id=original.client_action_id,
    )
    assert stopped.run.status == expected_status
    if expected_status == "cancelled":
        assert [step.status for step in stopped.run.steps] == [
            "completed",
            "stopped",
            "pending",
        ]
        assert stopped.run.steps[1].safe_failure_code == "PLAN_CANCELLED"
    else:
        assert stopped.run.steps[0].safe_failure_code == "STEP_FAILED"
    assert stopped.run.pending_cancel_request_id is None
    assert cancel.request_id in stopped.run.cancel_request_ids
    assert len(adjudicator.contexts) == 1

    # A retry after the reconciliation is a pure replay: no later step starts
    # and no effect/event is duplicated.
    replayed = await service.resume_owned(
        room_id="room_01",
        player_id="player_01",
        actor_id="pc_1",
        parent_action_id=original.client_action_id,
    )
    assert replayed.run == stopped.run
    assert len(adjudicator.contexts) == 1


@pytest.mark.asyncio
async def test_post_roll_retry_resolves_plan_once_without_duplicate_effects() -> None:
    module, engine_store, projector = runtime()
    adjudicator = RecordingAdjudicator(module.world_ref, check_step=0)
    engine = AdjudicationEngineService(
        engine_store,
        dice=DiceRoller(SequenceDiceSource([80, 1])),
    )
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=engine,
        player_view_projector=projector,
    )
    original = player_input("post-roll-parent")

    waiting = await service.start_or_resume(original, plan=plan(2))
    pending = waiting.latest_execution
    assert pending is not None and pending.pending_decision is not None
    rolled = await engine.decide(
        CheckDecisionRequest(
            request_id="post-roll-parent:select",
            room_id="room_01",
            player_id="player_01",
            source_revision=pending.view_revision,
            decision_id=pending.pending_decision.decision_id,
            decision_version=pending.pending_decision.decision_version,
            choice=SelectCheckChoice(candidate_id="spot"),
        )
    )
    assert rolled.status == "awaiting_post_roll_decision"
    check_run = rolled.check_run
    assert check_run is not None
    accept = PostRollDecisionRequest(
        request_id="post-roll-parent:accept",
        room_id="room_01",
        player_id="player_01",
        source_revision=rolled.view_revision,
        check_id=check_run.check_id,
        check_version=check_run.version,
        option_id="push-once",
        push_adjudication=PushAdjudication(method_description="换一种方式继续调查"),
    )
    resolved = await engine.decide_post_roll(accept)
    replay = await engine.decide_post_roll(accept)
    assert resolved.status == "resolved"
    assert replay == resolved

    completed = await service.start_or_resume(original, plan=plan(2))
    assert completed.run.status == "awaiting_narration"
    assert completed.run.current_step_index == 2
    assert len(engine_store.inspect_domain_events("room_01")) == 7
    assert [
        event.type for event in engine_store.inspect_domain_events("room_01")
    ].count("action.succeeded") == 2


@pytest.mark.asyncio
async def test_failed_plan_step_leaves_a_run_that_can_still_be_loaded() -> None:
    """A step that fails must not persist a terminal run that still holds a lease.

    `ActionPlanRun` rejects that combination, and `model_copy` does not re-run
    validators — so writing it produces a row no store can read back. The next
    load raises a bare ValidationError, which the transport can only report as
    TURN_CONTRACT_INVALID, and every retry of the same action hits it again.
    """

    module, engine_store, projector = runtime()
    adjudicator = RecordingAdjudicator(module.world_ref, check_step=0)
    # spot is 60; an 80 fails the regular-difficulty check.
    engine = AdjudicationEngineService(
        engine_store,
        dice=DiceRoller(SequenceDiceSource([80])),
    )
    store = InMemoryActionPlanRunStore()
    service = ActionPlanOrchestrator(
        store=store,
        adjudicator=adjudicator,
        executor=engine,
        player_view_projector=projector,
    )
    original = player_input("failed-step-parent")

    waiting = await service.start_or_resume(original, plan=plan(2))
    pending = waiting.latest_execution
    assert pending is not None and pending.pending_decision is not None
    rolled = await engine.decide(
        CheckDecisionRequest(
            request_id="failed-step-parent:select",
            room_id="room_01",
            player_id="player_01",
            source_revision=pending.view_revision,
            decision_id=pending.pending_decision.decision_id,
            decision_version=pending.pending_decision.decision_version,
            choice=SelectCheckChoice(candidate_id="spot"),
        )
    )
    assert rolled.status == "awaiting_post_roll_decision"
    assert rolled.check_run is not None
    accepted = await engine.decide_post_roll(
        PostRollDecisionRequest(
            request_id="failed-step-parent:accept",
            room_id="room_01",
            player_id="player_01",
            source_revision=rolled.view_revision,
            check_id=rolled.check_run.check_id,
            check_version=rolled.check_run.version,
            option_id="accept-current",
        )
    )
    assert accepted.outcome == "failure"

    stopped = await service.resume_owned(
        room_id="room_01",
        player_id="player_01",
        actor_id="pc_1",
        parent_action_id=original.client_action_id,
    )

    assert stopped.run.status == "stopped"
    assert stopped.run.steps[0].safe_failure_code == "STEP_FAILED"
    assert stopped.run.lease_owner is None
    assert stopped.run.lease_expires_at is None

    # What a persisting store does on every read. `model_copy` skips validators,
    # so only this round trip catches an invariant the writer broke.
    persisted = await store.load("room_01", original.client_action_id)
    assert persisted is not None
    ActionPlanRun.model_validate_json(persisted.model_dump_json())

    # And the stopped plan must still be reloadable through the normal path.
    assert await service.get_run("room_01", original.client_action_id) is not None


@pytest.mark.asyncio
async def test_engine_commit_before_plan_cursor_update_reconciles_without_replay() -> (
    None
):
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

    recovered = await service.start_or_resume(
        original,
        plan=plan(2),
        worker_id="crashed-worker",
    )

    assert recovered.run.status == "awaiting_narration"
    assert len(engine_store.inspect_domain_events("room_01")) == 2
    assert [context.step_index for context in adjudicator.contexts] == [0, 1]
    assert crashing.crashed is True


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

    resumed = await service.start_or_resume(original, plan=plan(2))

    assert resumed.run.status == "awaiting_narration"
    assert [context.player_view.revision for context in adjudicator.contexts] == [
        "0",
        "1",
        "2",
    ]
    assert adjudicator.contexts[1].previous_rejection == (
        "SOURCE_REVISION_STALE: 动作基于过期的玩家视图，请刷新后重试"
    )
    assert len(engine_store.inspect_domain_events("room_01")) == 3


@pytest.mark.asyncio
async def test_second_step_provider_failure_retries_from_same_cursor() -> None:
    module, engine_store, projector = runtime()
    adjudicator = FailSecondStepOnceAdjudicator(module.world_ref)
    observer = RecordingStepFailureObserver()
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=projector,
        on_step_failure=observer,
    )
    original = player_input("provider-retry-parent")

    failed = await service.start_or_resume(original, plan=plan(2))

    assert failed.run.status == "retryable_failure"
    assert failed.run.current_step_index == 1
    assert [step.status for step in failed.run.steps] == ["completed", "pending"]
    assert failed.run.steps[1].safe_failure_code == "STEP_ADJUDICATOR_FAILED"
    assert len(engine_store.inspect_domain_events("room_01")) == 1
    assert "temporary provider outage" not in failed.run.model_dump_json()
    assert len(observer.failures) == 1
    diagnostic = observer.failures[0]
    assert diagnostic.correlation_id == original.client_action_id
    assert diagnostic.plan_id == failed.run.plan_id
    assert diagnostic.step_id == failed.run.steps[1].step_id
    assert diagnostic.step_index == 1
    assert diagnostic.attempt == 1
    assert diagnostic.duration_ms >= 0
    assert diagnostic.code == "STEP_ADJUDICATOR_FAILED"
    assert isinstance(diagnostic.error, RuntimeError)
    assert diagnostic.completed_steps == 1
    assert diagnostic.authoritative_submitted is False

    recovered = await service.start_or_resume(original, plan=plan(2))

    assert recovered.run.status == "awaiting_narration"
    assert recovered.run.current_step_index == 2
    assert [context.step_index for context in adjudicator.contexts] == [0, 1, 1]
    assert [context.player_view.revision for context in adjudicator.contexts] == [
        "0",
        "1",
        "1",
    ]
    assert len(engine_store.inspect_domain_events("room_01")) == 2


@pytest.mark.asyncio
async def test_step_failure_observer_error_does_not_change_plan_failure_state() -> None:
    """日志或监控不可用时，仍须保留前序提交并安全停在当前未提交步骤。"""

    module, engine_store, projector = runtime()
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=FailSecondStepOnceAdjudicator(module.world_ref),
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=projector,
        on_step_failure=RaisingStepFailureObserver(),
    )

    failed = await service.start_or_resume(
        player_input("observer-failure-parent"),
        plan=plan(2),
    )

    assert failed.run.status == "retryable_failure"
    assert [step.status for step in failed.run.steps] == ["completed", "pending"]
    assert failed.run.steps[1].safe_failure_code == "STEP_ADJUDICATOR_FAILED"
    assert len(engine_store.inspect_domain_events("room_01")) == 1


@pytest.mark.asyncio
async def test_classified_step_failure_preserves_code_and_original_cause() -> None:
    module, engine_store, projector = runtime()
    observer = RecordingStepFailureObserver()
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=ClassifiedSecondStepAdjudicator(module.world_ref),
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=projector,
        on_step_failure=observer,
    )

    failed = await service.start_or_resume(
        player_input("classified-provider-parent"),
        plan=plan(2),
    )

    assert failed.run.status == "retryable_failure"
    assert failed.run.steps[1].safe_failure_code == "MODEL_UPSTREAM_UNAVAILABLE"
    assert [step.status for step in failed.run.steps] == ["completed", "pending"]
    assert len(engine_store.inspect_domain_events("room_01")) == 1
    assert len(observer.failures) == 1
    assert observer.failures[0].code == "MODEL_UPSTREAM_UNAVAILABLE"
    assert isinstance(observer.failures[0].error, RuntimeError)


@pytest.mark.asyncio
async def test_retryable_failure_can_be_superseded_by_the_next_utterance() -> None:
    """可重试失败必须能被同一名玩家的下一句话顶替掉。

    `ActionPlanTurnApplication.start` 靠 `cancel_remaining` 让位，而让位的前提是
    这条死计划落在可取消边界上：可重试失败的**当前**步恒为 pending，即使更早的
    步骤已经提交过效果——那正是 cancel_remaining 的语义，保留已提交的、放弃剩下
    的。这里连同「先前效果不被回滚」一起钉住，免得以后有人把失败步改成非
    pending，让顶替静默退化成 PLAN_CANCEL_NOT_AT_BOUNDARY，玩家又被锁回「只能
    原样重发同一句」。
    """

    module, engine_store, projector = runtime()
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=FailSecondStepOnceAdjudicator(module.world_ref),
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=projector,
    )
    original = player_input("supersede-parent")

    failed = await service.start_or_resume(original, plan=plan(2))
    assert failed.run.status == "retryable_failure"
    assert [step.status for step in failed.run.steps] == ["completed", "pending"]

    superseded = await service.cancel_remaining(
        CancelActionPlanRequest(
            request_id="auto-supersede-supersede-parent",
            room_id=original.room_id,
            player_id=original.player_id,
            actor_id=original.actor_id,
            parent_action_id=original.client_action_id,
        )
    )

    assert superseded.status == "cancelled"
    # 第一步已提交的效果留在世界里，没有被顶替连带回滚。
    assert len(engine_store.inspect_domain_events("room_01")) == 1


@pytest.mark.asyncio
async def test_invalid_second_step_fails_closed_before_engine_commit() -> None:
    module, engine_store, projector = runtime()
    adjudicator = RejectSecondStepAdjudicator(module.world_ref)
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=projector,
    )

    failed = await service.start_or_resume(
        player_input("invalid-step-parent"),
        plan=plan(2),
    )

    assert failed.run.status == "retryable_failure"
    assert failed.run.current_step_index == 1
    assert [step.status for step in failed.run.steps] == ["completed", "pending"]
    assert failed.run.steps[1].adjudication is None
    assert failed.run.steps[1].safe_failure_code == "STEP_ADJUDICATOR_FAILED"
    assert len(engine_store.inspect_domain_events("room_01")) == 1


@pytest.mark.asyncio
async def test_engine_rejection_is_repaired_once_instead_of_stopping_the_plan() -> None:
    module, engine_store, projector = runtime()
    adjudicator = MissingTargetAdjudicator(module.world_ref)
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=projector,
    )

    settled = await service.start_or_resume(
        player_input("repairable-step-parent"),
        plan=plan(2),
    )

    assert settled.run.status == "awaiting_narration"
    assert [step.status for step in settled.run.steps] == ["completed", "completed"]
    # Step 2 was adjudicated twice: the refused proposal, then the repair that
    # carried the Engine's own reason back to the adjudicator.
    step_two = [context for context in adjudicator.contexts if context.step_index == 1]
    assert step_two[0].previous_rejection is None
    assert step_two[1].previous_rejection is not None
    assert step_two[1].previous_rejection.startswith(
        "TARGET_UNAVAILABLE: 当前目标不可用于这次行动"
    )
    assert "keeper_capabilities" in step_two[1].previous_rejection
    assert settled.run.steps[1].repair_attempts == 1
    assert settled.run.steps[1].last_validation_code == "TARGET_UNAVAILABLE"
    assert settled.run.steps[1].last_validation_message == "当前目标不可用于这次行动"
    # The repair reuses the frozen step identity; nothing is committed twice.
    assert len({context.step_request_id for context in step_two}) == 1
    assert len(engine_store.inspect_domain_events("room_01")) == 2


@pytest.mark.asyncio
async def test_engine_rejection_repair_is_attempted_at_most_once() -> None:
    module, engine_store, projector = runtime()
    adjudicator = MissingTargetAdjudicator(module.world_ref, repairs=False)
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=projector,
    )

    failed = await service.start_or_resume(
        player_input("unrepairable-step-parent"),
        plan=plan(2),
    )

    assert failed.run.status == "needs_clarification"
    assert failed.run.steps[1].safe_failure_code == "REPAIR_BUDGET_EXHAUSTED"
    assert failed.run.steps[1].repair_attempts == 1
    assert failed.run.steps[1].last_validation_code == "TARGET_UNAVAILABLE"
    assert failed.run.steps[1].last_validation_message == "当前目标不可用于这次行动"
    assert (
        len([context for context in adjudicator.contexts if context.step_index == 1])
        == 2
    )
    # The first step stays committed; the refused one never reaches the Engine.
    assert len(engine_store.inspect_domain_events("room_01")) == 1


@pytest.mark.asyncio
async def test_plan_semantic_drift_stops_before_second_engine_submit() -> None:
    module, engine_store, projector = runtime()
    adjudicator = SemanticallyDriftingRepairAdjudicator(module.world_ref)
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=projector,
    )

    result = await service.start_or_resume(
        player_input("semantic-drift-parent"),
        plan=plan(2),
    )

    assert result.run.status == "needs_clarification"
    assert [step.status for step in result.run.steps] == ["completed", "stopped"]
    assert result.run.steps[1].safe_failure_code == (
        "SEMANTIC_REPAIR_REQUIRES_CLARIFICATION"
    )
    assert result.run.steps[1].repair_baseline is None
    assert result.run.steps[1].repair_feedback is None
    assert "keeper-only" not in result.run.model_dump_json()
    assert "hidden target evidence" not in result.run.model_dump_json()
    assert len(engine_store.inspect_domain_events("room_01")) == 1


@pytest.mark.parametrize(
    ("repairability", "expected_status"),
    (
        ("requires_player_choice", "needs_clarification"),
        ("hard_reject", "stopped"),
    ),
)
@pytest.mark.asyncio
async def test_non_repairable_validation_stops_without_recalling_agent(
    repairability: Repairability,
    expected_status: str,
) -> None:
    module, engine_store, projector = runtime()
    adjudicator = RecordingAdjudicator(module.world_ref)
    executor = ValidationRejectingExecutor(
        AdjudicationEngineService(engine_store),
        repairability=repairability,
        rejected_summary="完成步骤 2",
    )
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=executor,
        player_view_projector=projector,
    )

    result = await service.start_or_resume(
        player_input(f"{repairability}-parent"),
        plan=plan(2),
    )

    current = result.run.steps[1]
    assert result.run.status == expected_status
    assert [step.status for step in result.run.steps] == ["completed", "stopped"]
    assert [context.step_index for context in adjudicator.contexts] == [0, 1]
    assert current.repair_attempts == 0
    assert current.safe_failure_code == "TEST_VALIDATION_REJECTION"
    assert current.last_validation_code == "TEST_VALIDATION_REJECTION"
    assert current.last_validation_message == "这次行动需要停下确认"
    assert "keeper-only" not in result.run.model_dump_json()
    assert len(engine_store.inspect_domain_events("room_01")) == 1


@pytest.mark.asyncio
async def test_zero_repair_budget_disables_plan_auto_repair() -> None:
    module, engine_store, projector = runtime()
    adjudicator = MissingTargetAdjudicator(module.world_ref)
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=projector,
        policy=ActionPlanPolicy(max_repair_attempts=0),
    )

    failed = await service.start_or_resume(
        player_input("repair-disabled-parent"),
        plan=plan(2),
    )

    assert failed.run.status == "needs_clarification"
    assert failed.run.steps[1].repair_attempts == 0
    assert failed.run.steps[1].safe_failure_code == "REPAIR_BUDGET_EXHAUSTED"
    assert (
        len([context for context in adjudicator.contexts if context.step_index == 1])
        == 1
    )
    assert len(engine_store.inspect_domain_events("room_01")) == 1


@pytest.mark.asyncio
async def test_plain_contract_error_is_not_treated_as_repairable() -> None:
    module, engine_store, projector = runtime()
    adjudicator = RecordingAdjudicator(module.world_ref)
    executor = ContractRejectingExecutor(AdjudicationEngineService(engine_store))
    service = ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=executor,
        player_view_projector=projector,
    )

    failed = await service.start_or_resume(
        player_input("contract-rejection-parent"),
        plan=plan(2),
    )

    assert failed.run.status == "needs_clarification"
    assert failed.run.steps[1].safe_failure_code == "STEP_ADJUDICATION_REJECTED"
    assert failed.run.steps[1].repair_attempts == 0
    assert [context.step_index for context in adjudicator.contexts] == [0, 1]
    assert len(engine_store.inspect_domain_events("room_01")) == 1


def test_plan_run_repair_fields_round_trip_and_old_json_uses_defaults() -> None:
    original = player_input("json-default-parent")
    created_at = datetime.now(UTC)
    plan_value = plan(2)
    run = ActionPlanRun(
        plan_id="plan-json-default",
        parent_action_id=original.client_action_id,
        parent_input_fingerprint=("0" * 64),
        parent_utterance=original.utterance,
        room_id=original.room_id,
        player_id=original.player_id,
        actor_id=original.actor_id,
        created_revision="0",
        policy_snapshot=ActionPlanPolicy(),
        plan=plan_value,
        steps=tuple(
            ActionPlanStepRun(
                step_id=f"step-{index}",
                step_request_id=f"request-{index}",
                step=step,
            )
            for index, step in enumerate(plan_value.steps)
        ),
        created_at=created_at,
        updated_at=created_at,
    )
    payload = run.model_dump(mode="json")
    payload["policy_snapshot"].pop("max_repair_attempts")
    for step_payload in payload["steps"]:
        step_payload.pop("repair_attempts")
        step_payload.pop("last_validation_code")
        step_payload.pop("last_validation_message")
        step_payload.pop("repair_baseline")
        step_payload.pop("repair_feedback")

    restored = ActionPlanRun.model_validate(payload)

    assert restored.policy_snapshot.max_repair_attempts == 1
    assert all(step.repair_attempts == 0 for step in restored.steps)
    assert all(step.last_validation_code is None for step in restored.steps)
    assert all(step.repair_baseline is None for step in restored.steps)
    assert all(step.repair_feedback is None for step in restored.steps)
    assert ActionPlanRun.model_validate_json(restored.model_dump_json()) == restored


def test_legacy_plan_run_restores_default_persistence_intent_as_omitted() -> None:
    original = player_input("legacy-persistence-parent")
    created_at = datetime.now(UTC)
    plan_value = plan(2)
    adjudication = ActionAdjudication(
        request_id="request-0",
        source_revision="0",
        actor_id=original.actor_id,
        summary="前往旅店",
        target=ActionTarget(kind="location", id="street"),
        method=ActionMethod(family="travel", description="前往旅店"),
        check=NoAdjudicationCheck(),
        success_effects=(EnterLocationEffect(location_id="inn"),),
    )
    run = ActionPlanRun(
        plan_id="legacy-persistence-plan",
        parent_action_id=original.client_action_id,
        parent_input_fingerprint=("0" * 64),
        parent_utterance=original.utterance,
        room_id=original.room_id,
        player_id=original.player_id,
        actor_id=original.actor_id,
        created_revision="0",
        policy_snapshot=ActionPlanPolicy(),
        plan=plan_value,
        steps=(
            ActionPlanStepRun(
                step_id="step-0",
                step_request_id="request-0",
                step=plan_value.steps[0],
                status="ready",
                source_revision="0",
                adjudication=adjudication,
            ),
            ActionPlanStepRun(
                step_id="step-1",
                step_request_id="request-1",
                step=plan_value.steps[1],
            ),
        ),
        created_at=created_at,
        updated_at=created_at,
    )

    legacy_payload = run.model_dump(mode="json")
    stored_adjudication = legacy_payload["steps"][0]["adjudication"]
    assert stored_adjudication["persistence_intent"] == "none"
    assert "persistence_intent_explicit_marker" not in stored_adjudication

    restored = ActionPlanRun.from_persistence_json_dict(legacy_payload)

    restored_adjudication = restored.steps[0].adjudication
    assert restored_adjudication is not None
    assert restored_adjudication.persistence_intent == "none"
    assert restored_adjudication.persistence_intent_explicit is False


@pytest.mark.asyncio
async def test_safe_validation_feedback_maximum_length_fits_step_context() -> None:
    _, _, projector = runtime()
    original = player_input("max-feedback-parent")
    context = ActionPlanStepContext(
        player_input=original,
        plan_id="max-feedback-plan",
        plan_goal="验证最长安全反馈",
        step_index=0,
        step_request_id="max-feedback-step",
        step=ActionPlanStep(kind="action", semantic_goal="验证最长安全反馈"),
        player_view=await projector.project(original),
        previous_rejection=f"{'C' * 100}: {'R' * 512}",
    )

    assert context.previous_rejection is not None
    assert len(context.previous_rejection) == 614


@pytest.mark.asyncio
async def test_repair_hint_fits_the_step_context() -> None:
    """最长的一条拒绝理由加上最长的一条修复指引仍要装得下（#313）。

    `previous_rejection` 有 max_length，而修复指引是拼在拒绝理由后面的。指引写长了
    应该在这里红，而不是等到线上某次修复重试直接抛 ValidationError——那会把一次本
    来能救回来的回合变成 TURN_CONTRACT_INVALID。
    """

    _, _, projector = runtime()
    original = player_input("max-hint-parent")
    longest_hint = max(_REPAIR_HINTS.values(), key=len)
    worst_case = f"{'C' * 100}: {'R' * 512}\n{longest_hint}"

    context = ActionPlanStepContext(
        player_input=original,
        plan_id="max-hint-plan",
        plan_goal="验证最长修复指引",
        step_index=0,
        step_request_id="max-hint-step",
        step=ActionPlanStep(kind="action", semantic_goal="验证最长修复指引"),
        player_view=await projector.project(original),
        previous_rejection=worst_case,
    )

    assert context.previous_rejection == worst_case


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
async def test_expired_room_reservation_stops_blocking_the_room() -> None:
    """占用必须能自己过期，否则一次没走到释放路径的失败就把房间永久锁死。

    去掉 store 里的 TTL 判断，这个测试会停在 ActionPlanBusyError 上。
    """

    service, _, _, store, _ = orchestrator()
    first = player_input("first-parent")
    await service.start_or_resume(
        first,
        plan=plan(4),
        worker_id="worker-1",
        auto_continue=False,
    )

    # 把这次占用推到 TTL 之外。持久化侧对应的是 UPDATE 掉 reservation.updated_at，
    # 内存 store 的占用时间戳就取自 run.updated_at，所以改这里等价。
    key = (first.room_id, first.client_action_id)
    store._runs[key] = store._runs[key].model_copy(
        update={"updated_at": datetime.now(UTC) - timedelta(minutes=6)},
    )

    assert await store.load_active_for_room(first.room_id) is None

    second_service, _, _, _, _ = orchestrator(action_plan_store=store)
    taken_over = await second_service.start_or_resume(
        player_input("second-parent", "另一个行动"),
        plan=plan(2),
    )
    assert taken_over.run.parent_action_id == "second-parent"


@pytest.mark.asyncio
async def test_reservation_within_ttl_still_blocks_the_room() -> None:
    """TTL 不能顺手把「玩家正在思考」也判成过期。

    `waiting_for_player` 同样占着房间，5 分钟以内必须原样挡住——否则占用会在人
    还在挑技能时被抽走，随后 CAS 抛 PLAN_RESERVATION_LOST 把回合打死。
    """

    service, _, _, store, _ = orchestrator()
    first = player_input("first-parent")
    await service.start_or_resume(
        first,
        plan=plan(4),
        worker_id="worker-1",
        auto_continue=False,
    )

    key = (first.room_id, first.client_action_id)
    store._runs[key] = store._runs[key].model_copy(
        update={"updated_at": datetime.now(UTC) - timedelta(minutes=4)},
    )

    assert await store.load_active_for_room(first.room_id) is not None

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

    assert isinstance(result, SingleActionTurnResult)
    assert result.execution.status == "resolved"
    assert result.execution.action_request_id == original.client_action_id
    assert await store.load("room_01", original.client_action_id) is None
    assert len(engine_store.inspect_domain_events("room_01")) == 1


def single_action_decision(
    *, world_ref: str, valid_target: bool
) -> SingleActionDecision:
    return SingleActionDecision(
        adjudication=ActionAdjudication(
            request_id="untrusted",
            source_revision="untrusted",
            actor_id="untrusted",
            summary="检查当前环境",
            target=ActionTarget(
                kind="world",
                id=world_ref if valid_target else "missing-target",
            ),
            method=ActionMethod(family="observe", description="检查当前环境"),
            check=NoAdjudicationCheck(),
            success_effects=(NarrativeOnlyEffect(),),
        )
    )


def single_travel_decision(*, target_id: str) -> SingleActionDecision:
    return SingleActionDecision(
        adjudication=ActionAdjudication(
            request_id="untrusted",
            source_revision="untrusted",
            actor_id="untrusted",
            summary="前往墓地",
            target=ActionTarget(kind="location", id=target_id),
            method=ActionMethod(family="travel", description="前往墓地"),
            check=NoAdjudicationCheck(),
            success_effects=(EnterLocationEffect(location_id=target_id),),
        )
    )


@pytest.mark.asyncio
async def test_single_action_auto_repair_succeeds_without_creating_plan_run() -> None:
    module, engine_store, projector = runtime()
    plan_store = InMemoryActionPlanRunStore()
    engine = AdjudicationEngineService(engine_store)
    repair_adjudicator = VisibleTargetRepairAdjudicator(module.world_ref)
    orchestrator_service = ActionPlanOrchestrator(
        store=plan_store,
        adjudicator=repair_adjudicator,
        executor=engine,
        player_view_projector=projector,
    )
    dispatcher = HostTurnDecisionExecutor(
        plan_orchestrator=orchestrator_service,
        executor=engine,
        player_view_projector=projector,
        repair_adjudicator=repair_adjudicator,
        policy=ActionPlanPolicy(),
    )
    original = player_input("single-repair-parent", "检查书架")
    decision = single_action_decision(world_ref=module.world_ref, valid_target=False)
    decision = decision.model_copy(
        update={
            "adjudication": decision.adjudication.model_copy(
                update={
                    "summary": "检查书架",
                    "target": ActionTarget(kind="entity", id="missing-bookshelf"),
                    "method": ActionMethod(family="observe", description="检查书架"),
                },
                deep=True,
            )
        },
        deep=True,
    )

    result = await dispatcher.execute(
        original,
        decision,
    )

    assert isinstance(result, SingleActionTurnResult)
    assert result.execution.status == "resolved"
    assert result.execution.action_request_id == original.client_action_id
    assert len(repair_adjudicator.contexts) == 1
    context = repair_adjudicator.contexts[0]
    assert context.step_request_id == original.client_action_id
    assert context.previous_rejection is not None
    assert context.previous_rejection.startswith(
        "TARGET_UNAVAILABLE: 当前目标不可用于这次行动"
    )
    # #313：光有错误码定位不到问题，指引必须跟着一起回到修复裁决器。
    assert "keeper_capabilities" in context.previous_rejection
    assert await plan_store.load(original.room_id, original.client_action_id) is None
    assert len(engine_store.inspect_domain_events(original.room_id)) == 1


@pytest.mark.asyncio
async def test_single_travel_repair_with_changed_effect_requires_clarification() -> (
    None
):
    module, engine_store, projector = runtime()
    plan_store = InMemoryActionPlanRunStore()
    engine = AdjudicationEngineService(engine_store)
    repair_adjudicator = RecordingAdjudicator(module.world_ref)
    orchestrator_service = ActionPlanOrchestrator(
        store=plan_store,
        adjudicator=repair_adjudicator,
        executor=engine,
        player_view_projector=projector,
    )
    dispatcher = HostTurnDecisionExecutor(
        plan_orchestrator=orchestrator_service,
        executor=engine,
        player_view_projector=projector,
        repair_adjudicator=repair_adjudicator,
        policy=ActionPlanPolicy(),
    )
    original = player_input("single-travel-repair", "前往墓地")

    result = await dispatcher.execute(
        original,
        single_travel_decision(target_id="missing-location"),
    )

    assert isinstance(result, SingleActionClarificationResult)
    assert result.player_safe_reason == "修复方案可能改变原本行动，需要玩家确认下一步"
    assert len(repair_adjudicator.contexts) == 1
    context = repair_adjudicator.contexts[0]
    assert context.step.kind == "travel"
    assert context.previous_rejection is not None
    assert context.previous_rejection.startswith(
        "TARGET_UNAVAILABLE: 当前目标不可用于这次行动"
    )
    # #313：光有错误码定位不到问题，指引必须跟着一起回到修复裁决器。
    assert "keeper_capabilities" in context.previous_rejection
    assert await plan_store.load(original.room_id, original.client_action_id) is None
    assert engine_store.inspect_domain_events(original.room_id) == ()


@pytest.mark.asyncio
async def test_single_action_repair_budget_is_finite() -> None:
    module, engine_store, projector = runtime()
    plan_store = InMemoryActionPlanRunStore()
    engine = AdjudicationEngineService(engine_store)
    repair_adjudicator = AlwaysMissingTargetAdjudicator(module.world_ref)
    orchestrator_service = ActionPlanOrchestrator(
        store=plan_store,
        adjudicator=repair_adjudicator,
        executor=engine,
        player_view_projector=projector,
    )
    dispatcher = HostTurnDecisionExecutor(
        plan_orchestrator=orchestrator_service,
        executor=engine,
        player_view_projector=projector,
        repair_adjudicator=repair_adjudicator,
        policy=ActionPlanPolicy(max_repair_attempts=1),
    )
    original = player_input("single-repair-exhausted", "检查当前环境")

    result = await dispatcher.execute(
        original,
        single_action_decision(world_ref=module.world_ref, valid_target=False),
    )

    assert isinstance(result, SingleActionClarificationResult)
    assert "确认具体目标" in result.player_safe_reason
    assert len(repair_adjudicator.contexts) == 1
    assert await plan_store.load(original.room_id, original.client_action_id) is None
    assert engine_store.inspect_domain_events(original.room_id) == ()


@pytest.mark.parametrize("repairability", ("requires_player_choice", "hard_reject"))
@pytest.mark.asyncio
async def test_single_action_non_repairable_feedback_does_not_call_agent(
    repairability: Repairability,
) -> None:
    module, engine_store, projector = runtime()
    plan_store = InMemoryActionPlanRunStore()
    repair_adjudicator = RecordingAdjudicator(module.world_ref)
    engine = ValidationRejectingExecutor(
        AdjudicationEngineService(engine_store),
        repairability=repairability,
    )
    orchestrator_service = ActionPlanOrchestrator(
        store=plan_store,
        adjudicator=repair_adjudicator,
        executor=engine,
        player_view_projector=projector,
    )
    dispatcher = HostTurnDecisionExecutor(
        plan_orchestrator=orchestrator_service,
        executor=engine,
        player_view_projector=projector,
        repair_adjudicator=repair_adjudicator,
    )
    original = player_input(f"single-{repairability}", "检查当前环境")

    result = await dispatcher.execute(
        original,
        single_action_decision(world_ref=module.world_ref, valid_target=True),
    )

    assert isinstance(result, SingleActionClarificationResult)
    assert result.player_safe_reason == "这次行动需要停下确认"
    assert repair_adjudicator.contexts == []
    assert await plan_store.load(original.room_id, original.client_action_id) is None
    assert engine_store.inspect_domain_events(original.room_id) == ()


@pytest.mark.asyncio
async def test_single_action_reconciles_commit_response_failure_without_repair() -> (
    None
):
    module, engine_store, projector = runtime()
    plan_store = InMemoryActionPlanRunStore()
    repair_adjudicator = RecordingAdjudicator(module.world_ref)
    executor = CrashAfterCommitExecutor(AdjudicationEngineService(engine_store))
    orchestrator_service = ActionPlanOrchestrator(
        store=plan_store,
        adjudicator=repair_adjudicator,
        executor=executor,
        player_view_projector=projector,
    )
    dispatcher = HostTurnDecisionExecutor(
        plan_orchestrator=orchestrator_service,
        executor=executor,
        player_view_projector=projector,
        repair_adjudicator=repair_adjudicator,
    )
    original = player_input("single-reconcile-parent", "检查当前环境")

    result = await dispatcher.execute(
        original,
        single_action_decision(world_ref=module.world_ref, valid_target=True),
    )

    assert isinstance(result, SingleActionTurnResult)
    assert result.execution.action_request_id == original.client_action_id
    assert repair_adjudicator.contexts == []
    assert len(engine_store.inspect_domain_events(original.room_id)) == 1


@pytest.mark.asyncio
async def test_action_plan_persistent_empty_effect_is_repaired_once() -> None:
    service, adjudicator, _, _, engine_store = orchestrator(
        adjudicator=PersistentRepairAdjudicator("coc-7e")
    )
    result = await service.start_or_resume(
        player_input("persistent-repair"),
        plan=ActionPlan(
            goal="击晕守墓人",
            steps=(
                ActionPlanStep(kind="action", semantic_goal="击晕守墓人"),
                ActionPlanStep(kind="dialogue", semantic_goal="继续行动"),
            ),
        ),
    )
    assert result.run.status == "awaiting_narration"
    assert len([c for c in adjudicator.contexts if c.step_index == 0]) == 2
    assert result.latest_execution is not None
    assert result.latest_execution.committed_results[0].state_value == "unconscious"
    assert len(engine_store.inspect_domain_events("room_01")) == 4


@pytest.mark.asyncio
async def test_action_plan_persistent_empty_effect_twice_needs_clarification() -> None:
    service, adjudicator, _, _, engine_store = orchestrator(
        adjudicator=PersistentEmptyAdjudicator("coc-7e")
    )
    result = await service.start_or_resume(
        player_input("persistent-clarification"),
        plan=ActionPlan(
            goal="击晕守墓人",
            steps=(
                ActionPlanStep(kind="action", semantic_goal="击晕守墓人"),
                ActionPlanStep(kind="dialogue", semantic_goal="不应执行"),
            ),
        ),
    )
    assert result.run.status == "needs_clarification"
    assert result.run.steps[0].status == "stopped"
    assert result.run.steps[1].status == "pending"
    assert len(engine_store.inspect_domain_events("room_01")) == 0
    assert len([c for c in adjudicator.contexts if c.step_index == 0]) == 2


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
async def test_needs_clarification_can_be_cancelled_without_running_later_steps() -> (
    None
):
    service, _, _, _, engine_store = orchestrator(
        adjudicator=ClarificationAdjudicator()
    )
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
async def test_progress_delivery_failure_does_not_change_authoritative_execution() -> (
    None
):
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


V3_FIXTURE = (
    ROOT
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)


class SleepAfterTravelAdjudicator:
    """去旅店 + 睡一觉：第二步推进时间，第一步没有。"""

    async def adjudicate(self, context):
        effects = (
            (NarrativeOnlyEffect(),)
            if context.step_index == 0
            else (
                AdvanceWorldTimeEffect(to_point_id="hour_18"),
                AdvanceWorldTimeEffect(to_point_id="hour_20"),
            )
        )
        return ActionAdjudication(
            request_id="model-cannot-control-this",
            source_revision="model-cannot-control-this",
            actor_id="model-cannot-control-this",
            summary=context.step.semantic_goal,
            target=ActionTarget(kind="location", id=context.player_view.scene.id),
            method=ActionMethod(
                family=context.step.kind,
                description=context.step.semantic_goal,
            ),
            check=NoAdjudicationCheck(),
            success_effects=effects,
        )


def v3_orchestrator(adjudicator):
    """Only a v3 room has a discrete timeline for a step to advance."""

    content = ModuleContentV3.model_validate_json(
        V3_FIXTURE.read_text(encoding="utf-8")
    )
    engine_store = InMemoryEngineStore()
    engine_store.register_room(
        module_content=content,
        initial_state=GameState(
            room_id="room_01",
            scene_id=content.initial_state.start_location_id,
            actors={
                "pc_1": ActorState(
                    player_id="player_01",
                    name="陈探员",
                    source_character_id="character_v3",
                    source_character_version=1,
                    state={"skills": {"spot-hidden": 60}},
                )
            },
            entities={},
        ),
    )
    return ActionPlanOrchestrator(
        store=InMemoryActionPlanRunStore(),
        adjudicator=adjudicator,
        executor=AdjudicationEngineService(engine_store),
        player_view_projector=PlayerViewProjector(RuleEngineService(engine_store)),
        lease_seconds=1,
    )


@pytest.mark.asyncio
async def test_narration_context_dates_each_step_by_its_own_clock() -> None:
    """去旅店发生在中午，睡觉才把时间推到夜里。

    叙事器拿到的是回合结束后的 PlayerView。只给它这一个时刻，它就会把整段都
    写在终局时钟上——「夜色浓稠，你推开旅店的门」，而玩家其实是正午出发的。
    """

    service = v3_orchestrator(SleepAfterTravelAdjudicator())
    original = player_input("inn-and-sleep")
    sleep_plan = ActionPlan(
        goal="前往镇上的旅店并睡一觉",
        steps=(
            ActionPlanStep(kind="travel", semantic_goal="前往镇上的旅店"),
            ActionPlanStep(kind="rest", semantic_goal="在旅店睡一觉"),
        ),
    )

    await service.start_or_resume(original, plan=sleep_plan)
    context = await service.build_narration_context(original)

    assert context.opening_world_time is not None
    assert (
        context.opening_world_time.hour_of_day,
        context.opening_world_time.time_of_day,
    ) == (
        12,
        "day",
    )
    clocks = [
        (step.world_time_after.hour_of_day, step.world_time_after.time_of_day)
        for step in context.completed_steps
    ]
    assert clocks == [(12, "day"), (20, "night")]
    # The final view is still the post-turn state; it is simply no longer the
    # only clock the Narrator can see.
    assert context.player_view.world.hour_of_day == 20


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


@pytest.mark.asyncio
async def test_narrator_rejects_missing_required_evidence() -> None:
    service, _, _, _, _ = orchestrator()
    original = player_input()
    await service.start_or_resume(original, plan=plan(2))
    context = await service.build_narration_context(original)
    required_ref = context.allowed_evidence_refs[0]
    evidence = NarrationEvidence(
        ref=required_ref,
        kind="entity_discovered",
        subject_id="crypt_entrance",
        subject_name="石板下的地穴入口",
        subject_aliases=("地穴入口",),
        description="一块沉重石板遮住了向下的通道。",
        required_in_narration=True,
    )
    first_step = context.completed_steps[0].model_copy(
        update={"narration_evidence": (evidence,)}, deep=True
    )
    context = context.model_copy(
        update={
            "completed_steps": (first_step, *context.completed_steps[1:]),
            "narration_evidence": (evidence,),
        },
        deep=True,
    )

    with pytest.raises(ActionPlanNarrationValidationError) as raised:
        await ActionPlanNarrator(MissingRequiredEvidenceNarrationModel()).narrate(
            context
        )

    assert raised.value.reason == "required_evidence_missing"

    with pytest.raises(ActionPlanNarrationValidationError) as claimed_but_omitted:
        await ActionPlanNarrator(
            ClaimsButOmitsRequiredEvidenceNarrationModel()
        ).narrate(context)

    assert claimed_but_omitted.value.reason == "required_evidence_missing"

    # A natural narration that clearly names a safe alias is authoritative
    # enough for the service to record the required public ref itself.
    alias_output = await ActionPlanNarrator(
        AliasRequiredEvidenceNarrationModel()
    ).narrate(context)
    assert alias_output.claimed_evidence_refs == (required_ref,)


@pytest.mark.asyncio
async def test_narrator_rejects_first_person_subject_in_prose() -> None:
    service, _, _, _, _ = orchestrator()
    original = player_input()
    await service.start_or_resume(original, plan=plan(2))
    context = await service.build_narration_context(original)

    with pytest.raises(ActionPlanNarrationValidationError) as raised:
        await ActionPlanNarrator(FirstPersonNarrationModel()).narrate(context)

    assert raised.value.reason == "subject_ownership"
