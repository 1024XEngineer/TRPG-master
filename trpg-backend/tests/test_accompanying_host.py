"""Production model adapter → rules → persistent companions, without keyword routing."""

from pathlib import Path

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionPlanStep,
    ActionTarget,
    ChangeEntityStateEffect,
    CheckDecisionRequest,
    EnterLocationEffect,
    ModuleContentV3,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PlayerInput,
    PlayerViewScope,
    PostRollDecisionRequest,
    RequiredAdjudicationCheck,
    SelectCheckChoice,
    SkillCheckCandidate,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    ActorState,
    AdjudicationEngineService,
    DiceRoller,
    InMemoryEngineStore,
    RuleEngineService,
    SequenceDiceSource,
)
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.host.application import PlayerViewProjector
from collaboration_framework.host.schemas import ActionPlanStepContext, MemoryContext

from app.adapters.openai_models import PromptActionPlanStepAdjudicator
from app.core.action_plan_turn import (
    _ModelStepAdjudicator,
    build_action_plan_turn_application,
    build_rule_once_adjudication,
)
from app.core.config import Settings

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "agent-collaboration-framework/docs/module-parser/examples/module-content-validation"
    / "幸福蛙蛙村/module-content-v3.json"
)


async def runtime(*, accompanying=False):
    content = ModuleContentV3.model_validate_json(FIXTURE.read_text())
    state = create_initial_game_state(
        content,
        room_id="companions",
        actors={
            "actor": ActorState(
                player_id="player",
                name="调查员",
                source_character_id="character",
                source_character_version=1,
                state={"skills": {}, "attributes": {"STR": 50}},
            ),
        },
    )
    state.entities["james"]["accompanying"] = accompanying
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    rules = RuleEngineService(store)
    engine = AdjudicationEngineService(store)
    # Arrive through the real travel events so the public reception map is revealed.
    # Merely changing scene_id no longer makes undiscovered destinations known.
    for destination in ("frog_resort", "resort_reception"):
        view = await rules.read(
            PlayerViewScope(room_id="companions", player_id="player", actor_id="actor")
        )
        await engine.submit(
            SubmitAdjudicationRequest(
                room_id="companions",
                player_id="player",
                adjudication=ActionAdjudication(
                    request_id=f"setup-{destination}",
                    source_revision=view.revision,
                    actor_id="actor",
                    summary="抵达前台了解公开地图",
                    target=ActionTarget(kind="location", id=destination),
                    method=ActionMethod(family="travel", description="沿公开路线前往前台"),
                    persistence_intent="location",
                    check=NoAdjudicationCheck(),
                    success_effects=(EnterLocationEffect(location_id=destination),),
                ),
            )
        )
    return store, rules, engine


async def context_for(rules, utterance, request_id="action", kind="travel"):
    player = PlayerInput(
        room_id="companions",
        player_id="player",
        actor_id="actor",
        client_action_id=request_id,
        utterance=utterance,
    )
    projector = PlayerViewProjector(rules)
    view = await projector.project(player)
    return ActionPlanStepContext(
        player_input=player,
        player_view=view,
        keeper_capabilities=await projector.keeper_capabilities(
            player, expected_revision=view.revision
        ),
        plan_id="plan",
        plan_goal=utterance,
        step_index=0,
        step_request_id=request_id,
        step=ActionPlanStep(kind=kind, semantic_goal=utterance),
    )


def travel(context, destination):
    return ActionAdjudication(
        request_id=context.step_request_id,
        source_revision=context.player_view.revision,
        actor_id=context.player_input.actor_id,
        summary=context.step.semantic_goal,
        target=ActionTarget(kind="location", id=destination),
        method=ActionMethod(family="travel", description=context.step.semantic_goal),
        persistence_intent="location",
        check=NoAdjudicationCheck(),
        success_effects=(EnterLocationEffect(location_id=destination),),
    )


class RecordingClient:
    def __init__(self, decide):
        self.decide = decide
        self.calls = []

    async def generate(self, *, schema_name, schema, instructions, input_payload):
        self.calls.append(input_payload)
        assert schema_name == "trpg_action_plan_step_adjudication"
        assert "accompanying" in instructions
        context = ActionPlanStepContext.model_validate(input_payload)
        return self.decide(context).to_json_dict()


@pytest.mark.parametrize("destination", ["guest_room", "staff_area"])
async def test_model_travel_keeps_one_authoritative_companion_move(destination):
    store, rules, engine = await runtime(accompanying=True)
    context = await context_for(
        rules, f"带詹姆斯进入{'客房1' if destination == 'guest_room' else '员工区'}"
    )
    client = RecordingClient(lambda ctx: travel(ctx, destination))
    decision = await _ModelStepAdjudicator(PromptActionPlanStepAdjudicator(client)).adjudicate(
        context
    )
    assert len(client.calls) == 1  # The former deterministic travel path would skip this.
    assert [effect.type for effect in decision.success_effects] == ["enter_location"]
    await engine.submit(
        SubmitAdjudicationRequest(room_id="companions", player_id="player", adjudication=decision)
    )
    state = store.inspect_state("companions")
    actual = "guest_room" if destination == "guest_room" else "resort_reception"
    assert state.scene_id == actual
    assert state.entities["james"].get("location_id", "resort_reception") == actual
    moves = [
        event for event in store.inspect_domain_events("companions") if event.type == "entity.moved"
    ]
    assert len(moves) == (1 if destination == "guest_room" else 0)
    if moves:
        assert moves[0].payload["reason"] == "accompanying"


async def test_negated_travel_reaches_model_and_does_not_move():
    store, rules, engine = await runtime(accompanying=True)
    context = await context_for(rules, "不要带詹姆斯进入客房1")

    def decline(ctx):
        return travel(ctx, "guest_room").model_copy(
            update={
                "target": ActionTarget(kind="location", id="resort_reception"),
                "method": ActionMethod(family="action", description="留在原地"),
                "persistence_intent": "none",
                "success_effects": (NarrativeOnlyEffect(),),
            }
        )

    client = RecordingClient(decline)
    decision = await _ModelStepAdjudicator(PromptActionPlanStepAdjudicator(client)).adjudicate(
        context
    )
    assert len(client.calls) == 1
    await engine.submit(
        SubmitAdjudicationRequest(room_id="companions", player_id="player", adjudication=decision)
    )
    assert store.inspect_state("companions").scene_id == "resort_reception"
    assert not any(
        event.type == "entity.moved" for event in store.inspect_domain_events("companions")
    )


class EmptyMemory:
    async def read_context(self, **kwargs):
        return MemoryContext(
            room_id=kwargs["room_id"],
            player_id=kwargs["player_id"],
            actor_id=kwargs["actor_id"],
            as_of_revision=kwargs["revision"],
        )


async def test_production_plan_establishes_companion_by_rule_then_travels_with_fresh_view():
    store, rules, engine = await runtime()

    class SemanticClient:
        def __init__(self):
            self.revisions = []

        async def generate(self, *, schema_name, schema, instructions, input_payload):
            if schema_name == "trpg_action_plan_narration":
                assert "keeper_capabilities" not in input_payload
                return {
                    "kind": "narration",
                    "text": "你站定，稍作停顿。",
                    "claimed_evidence_refs": [],
                    "suggested_actions": [],
                }
            if schema_name == "trpg_turn_plan":
                assert "keeper_capabilities" not in input_payload
                return {
                    "kind": "action_plan",
                    "goal": "尝试带詹姆斯去客房1",
                    "steps": [
                        {"kind": "travel", "semantic_goal": "尝试扛起詹姆斯同行"},
                        {"kind": "travel", "semantic_goal": "扶着詹姆斯去客房1"},
                    ],
                }
            assert schema_name == "trpg_action_plan_step_adjudication"
            ctx = ActionPlanStepContext.model_validate(input_payload)
            self.revisions.append(ctx.player_view.revision)
            assert ctx.keeper_capabilities is not None
            if ctx.step_index == 0:
                # Even kind=travel can select a character-state rule.
                return build_rule_once_adjudication(
                    player_input=ctx.player_input,
                    player_view=ctx.player_view,
                    capabilities=ctx.keeper_capabilities,
                    rule_id="carry_james_against_his_will",
                    option_id="carry-james",
                    summary=ctx.step.semantic_goal,
                ).to_json_dict()
            npc = next(npc for npc in ctx.player_view.scene.visible_entities if npc.id == "james")
            assert any(
                value.key == "accompanying" and value.value is True
                for value in npc.observable_state
            )
            return travel(ctx, "guest_room").to_json_dict()

    client = SemanticClient()
    app = build_action_plan_turn_application(
        store=store,
        engine=rules,
        adjudication_engine=engine,
        settings=Settings(host_model_provider="deepseek", deepseek_api_key="offline-test"),
        client=client,
        planner_client=client,
        memory_source=EmptyMemory(),
    )
    result = await app.start(
        room_id="companions",
        player_id="player",
        client_action_id="semantic-companion",
        utterance="尝试扛起詹姆斯，再扶着他去客房1",
    )
    assert result.status in {"awaiting_narration", "completed"}
    assert len(client.revisions) == 2
    assert client.revisions[0] != client.revisions[1]
    state = store.inspect_state("companions")
    assert state.scene_id == "guest_room"
    assert state.entities["james"]["location_id"] == "guest_room"
    assert state.entities["james"]["accompanying"] is True
    view = await rules.read(
        PlayerViewScope(room_id="companions", player_id="player", actor_id="actor")
    )
    assert any(npc.id == "james" for npc in view.scene.visible_entities)


@pytest.mark.parametrize("npc_id, agrees", [("emily", True), ("james", False)])
async def test_free_state_decision_reaches_engine_without_another_model_call(npc_id, agrees):
    store, rules, engine = await runtime()
    context = await context_for(rules, "请你接下来跟着我", kind="dialogue")
    if npc_id == "emily":
        assert "accompanying" not in store.inspect_state("companions").entities[npc_id]
    proposal = ActionAdjudication(
        request_id=context.step_request_id,
        source_revision=context.player_view.revision,
        actor_id=context.player_input.actor_id,
        summary="对方同意同行" if agrees else "对方不愿同行",
        target=ActionTarget(kind="entity", id=npc_id),
        method=ActionMethod(family="action", description="邀请同行"),
        persistence_intent="character_state" if agrees else "none",
        check=NoAdjudicationCheck(),
        success_effects=(
            ChangeEntityStateEffect(entity_id=npc_id, key="accompanying", value=True)
            if agrees
            else NarrativeOnlyEffect(),
        ),
    )
    client = RecordingClient(lambda ctx: proposal)
    decision = await _ModelStepAdjudicator(PromptActionPlanStepAdjudicator(client)).adjudicate(
        context
    )
    assert decision == proposal
    await engine.submit(
        SubmitAdjudicationRequest(room_id="companions", player_id="player", adjudication=decision)
    )
    assert len(client.calls) == 1
    assert store.inspect_state("companions").entities[npc_id].get("accompanying", False) is agrees
    next_context = await context_for(rules, "去客房1", request_id="travel")
    await engine.submit(
        SubmitAdjudicationRequest(
            room_id="companions",
            player_id="player",
            adjudication=travel(next_context, "guest_room"),
        )
    )
    npc = store.inspect_state("companions").entities[npc_id]
    assert npc.get("location_id", "resort_reception") == (
        "guest_room" if agrees else "resort_reception"
    )


@pytest.mark.parametrize("roll, succeeds", [(20, True), (90, False)])
async def test_model_binds_free_check_to_state_and_engine_waits_for_result(roll, succeeds):
    store, rules, _ = await runtime()
    engine = AdjudicationEngineService(store, dice=DiceRoller(SequenceDiceSource([roll])))
    context = await context_for(rules, "强行拖着对方跟我走", kind="action")
    proposal = ActionAdjudication(
        request_id=context.step_request_id,
        source_revision=context.player_view.revision,
        actor_id=context.player_input.actor_id,
        summary="尝试强行带人同行",
        target=ActionTarget(kind="entity", id="james"),
        method=ActionMethod(family="action", description="用力拖动对方"),
        persistence_intent="character_state",
        check=RequiredAdjudicationCheck(
            candidates=(
                SkillCheckCandidate(
                    candidate_id="force",
                    skill_id="STR",
                    difficulty="regular",
                    method_summary="用力量克服抵抗",
                    player_safe_reason="对方正在反抗",
                ),
            )
        ),
        success_effects=(
            ChangeEntityStateEffect(
                entity_id="james",
                key="accompanying",
                value=True,
            ),
        ),
        failure_effects=(NarrativeOnlyEffect(),),
    )
    client = RecordingClient(lambda ctx: proposal)
    decision = await _ModelStepAdjudicator(PromptActionPlanStepAdjudicator(client)).adjudicate(
        context
    )
    assert decision == proposal
    execution = await engine.submit(
        SubmitAdjudicationRequest(room_id="companions", player_id="player", adjudication=decision)
    )
    pending = execution.pending_decision
    assert pending is not None
    assert store.inspect_state("companions").entities["james"]["accompanying"] is False
    rolled = await engine.decide(
        CheckDecisionRequest(
            request_id="select",
            room_id="companions",
            player_id="player",
            source_revision=execution.view_revision,
            decision_id=pending.decision_id,
            decision_version=pending.decision_version,
            choice=SelectCheckChoice(candidate_id="force"),
        )
    )
    if rolled.status == "awaiting_post_roll_decision":
        assert store.inspect_state("companions").entities["james"]["accompanying"] is False
        check = rolled.check_run
        assert check is not None
        accept = next(
            option for option in check.post_roll_options if option.kind == "accept_result"
        )
        rolled = await engine.decide_post_roll(
            PostRollDecisionRequest(
                request_id="accept",
                room_id="companions",
                player_id="player",
                source_revision=rolled.view_revision,
                check_id=check.check_id,
                check_version=check.version,
                option_id=accept.option_id,
            )
        )
    assert rolled.outcome == ("success" if succeeds else "failure")
    assert store.inspect_state("companions").entities["james"]["accompanying"] is succeeds
    assert len(client.calls) == 1
