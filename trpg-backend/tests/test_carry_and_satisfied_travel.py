"""Production adapters and real engine; scripted model output, no external requests."""

from types import SimpleNamespace
from typing import cast

import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionPlan,
    ActionPlanStep,
    ActionTarget,
    ChangeEntityStateEffect,
    CheckDecisionRequest,
    EnterLocationEffect,
    ModuleContentV3,
    MoveEntityEffect,
    NarrativeOnlyEffect,
    NoAdjudicationCheck,
    PostRollDecisionRequest,
    RequiredAdjudicationCheck,
    RuleDecisionRef,
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
from collaboration_framework.host.application.satisfied_travel import satisfied_travel_adjudication
from collaboration_framework.host.schemas import ActionPlanRun, ActionPlanStepContext

from app.adapters.sqlalchemy_memory import _memory_from_game_event
from app.core.action_plan_turn import build_action_plan_turn_application
from app.core.config import Settings
from app.models.engine import GameEvent
from tests.test_accompanying_host import FIXTURE, EmptyMemory, context_for, travel


async def make_runtime(at="resort_reception"):
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
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    rules, engine = RuleEngineService(store), AdjudicationEngineService(store)
    for destination in ("frog_resort", at):
        ctx = await context_for(rules, "前往公开地点", f"setup-{destination}")
        await engine.submit(
            SubmitAdjudicationRequest(
                room_id="companions", player_id="player", adjudication=travel(ctx, destination)
            )
        )
    return store, rules, engine


def plan(*steps):
    return ActionPlan(
        goal="，然后".join(goal for _, goal in steps),
        steps=tuple(ActionPlanStep(kind=kind, semantic_goal=goal) for kind, goal in steps),
    )


class PlanClient:
    def __init__(self, planned, decide):
        self.planned, self.decide = planned, decide
        self.steps, self.narrations = [], []

    async def generate(self, *, schema_name, schema, instructions, input_payload):
        if schema_name == "trpg_turn_plan":
            return self.planned.to_json_dict()
        if schema_name == "trpg_action_plan_step_adjudication":
            ctx = ActionPlanStepContext.model_validate(input_payload)
            self.steps.append(ctx)
            return self.decide(ctx).to_json_dict()
        assert schema_name == "trpg_action_plan_narration"
        self.narrations.append(input_payload)
        scene = input_payload["player_view"]["scene"]
        results = [r for s in input_payload["completed_steps"] for r in s["committed_results"]]
        text = f"你来到{scene['name']}。" if any(r["kind"] == "location" for r in results) else ""
        inventory = {i["id"]: i["name"] for i in input_payload["player_view"]["inventory"]}
        acquired = [
            r["target_id"]
            for r in results
            if r["kind"] == "inventory" and r["target_id"] in inventory
        ]
        text += "".join(f"你随身带着{inventory[item]}。" for item in acquired)
        text += "".join(
            e["description"]
            for e in input_payload["narration_evidence"]
            if e["required_in_narration"]
        )
        return {
            "text": text or "你查看了周围。",
            "claimed_evidence_refs": input_payload["allowed_evidence_refs"],
            "claimed_inventory_ids": acquired,
        }


def application(store, rules, engine, client):
    return build_action_plan_turn_application(
        store=store,
        engine=rules,
        adjudication_engine=engine,
        settings=Settings(host_model_provider="deepseek", deepseek_api_key="offline"),
        client=client,
        planner_client=client,
        memory_source=EmptyMemory(),
    )


async def start(app, planned):
    return await app.start(
        room_id="companions", player_id="player", client_action_id="test", utterance=planned.goal
    )


@pytest.mark.parametrize("confirmation", [False, True])
async def test_production_already_here_is_short_success_without_new_travel(confirmation):
    store, rules, engine = await make_runtime()
    planned = plan(("travel", "前往别墅一层大厅"))

    def decide(ctx):
        proposal = travel(ctx, "resort_reception")
        return (
            proposal.model_copy(
                update={"persistence_intent": "none", "success_effects": (NarrativeOnlyEffect(),)}
            )
            if confirmation
            else proposal
        )

    client = PlanClient(planned, decide)
    app = application(store, rules, engine, client)
    before = len(store.inspect_domain_events("companions"))
    result = await start(app, planned)
    assert result.status == "awaiting_narration"
    assert result.narration.text == "你已经在一层接待大厅了。"
    assert not client.narrations
    assert not any(
        e.type.startswith("travel.") for e in store.inspect_domain_events("companions")[before:]
    )
    run = await app.get_plan("companions", "test")
    restored = ActionPlanRun.from_persistence_json_dict(run.to_persistence_json_dict())
    assert restored.steps[0].already_at_destination_id == "resort_reception"
    assert restored.steps[0].adjudication_execution is not None
    assert not restored.steps[0].adjudication_execution.committed_results
    assert (await start(app, planned)).narration.text == result.narration.text
    assert len(client.steps) == 1


@pytest.mark.parametrize(
    "destinations",
    [
        ("guest_corridor", "resort_reception"),
        ("resort_reception", "guest_corridor"),
        ("guest_corridor", "guest_corridor"),
    ],
)
async def test_each_travel_step_uses_current_location(destinations):
    store, rules, engine = await make_runtime()
    names = {"guest_corridor": "二楼客房走廊", "resort_reception": "别墅一层大厅"}
    planned = plan(*(("travel", f"前往{names[d]}") for d in destinations))
    client = PlanClient(planned, lambda ctx: travel(ctx, destinations[ctx.step_index]))
    app = application(store, rules, engine, client)
    before = len(store.inspect_domain_events("companions"))
    result = await start(app, planned)
    assert result.status == "awaiting_narration"
    origins = ["resort_reception", destinations[0]]
    assert [ctx.player_view.scene.id for ctx in client.steps] == origins
    assert store.inspect_state("companions").scene_id == destinations[-1]
    events = [
        e for e in store.inspect_domain_events("companions")[before:] if e.type == "travel.resolved"
    ]
    assert [e.payload["destination_id"] for e in events] == [
        d for origin, d in zip(origins, destinations, strict=True) if origin != d
    ]
    assert client.narrations  # Short confirmation cannot swallow a real arrival.
    run = await app.get_plan("companions", "test")
    assert [s.already_at_destination_id for s in run.steps] == [
        d if origin == d else None for origin, d in zip(origins, destinations, strict=True)
    ]


def pickup(ctx):
    return ActionAdjudication(
        request_id=ctx.step_request_id,
        source_revision=ctx.player_view.revision,
        actor_id="actor",
        summary=ctx.step.semantic_goal,
        target=ActionTarget(kind="entity", id="dream_frog_item"),
        method=ActionMethod(family="pick_up", description="捉起并携带一只青蛙"),
        persistence_intent="inventory",
        check=NoAdjudicationCheck(),
        success_effects=(MoveEntityEffect(entity_id="dream_frog_item", holder_actor_id="actor"),),
    )


async def test_capture_commits_backpack_before_travel_then_drop_preserves_instance():
    store, rules, engine = await make_runtime("frog_pond")
    planned = plan(("action", "尝试捉起并携带一只梦游青蛙"), ("travel", "带着青蛙前往别墅一层大厅"))

    def decide(ctx):
        assert ctx.player_view.scene.id == "frog_pond"
        if ctx.step_index == 1:
            assert any(i.id == "dream_frog_item" for i in ctx.player_view.inventory)
            assert not any(i.id == "dream_frog_item" for i in ctx.player_view.scene.loose_items)
            return travel(ctx, "resort_reception")
        assert (
            next(e for e in ctx.player_view.scene.visible_entities if e.id == "dream_frogs").kind
            == "object"
        )
        assert not any(
            e.kind == "npc" for e in ctx.player_view.scene.visible_entities if "frog" in e.id
        )
        assert any(i.id == "dream_frog_item" for i in ctx.player_view.scene.loose_items)
        return pickup(ctx)

    client = PlanClient(planned, decide)
    app = application(store, rules, engine, client)
    result = await start(app, planned)
    assert result.status == "awaiting_narration"
    assert len(client.steps) == 2
    assert client.steps[0].player_view.revision != client.steps[1].player_view.revision
    state = store.inspect_state("companions")
    item = state.item_instances["dream_frog_item"]
    assert item.custody.kind == "actor_inventory" and item.custody.ref_id == "actor"
    assert item.item_component.quantity == 1
    assert not state.entities["dream_frogs"].get("accompanying")
    assert state.entities["dream_frogs"].get("location_id", "frog_pond") == "frog_pond"
    assert "resort_map_layout" in state.discovered_facts
    assert len(client.narrations) == 1
    assert client.narrations[-1]["narration_evidence"]
    assert "一只梦游青蛙" in result.narration.text
    await start(app, planned)
    assert (
        store.inspect_state("companions").item_instances["dream_frog_item"].version == item.version
    )
    ctx = await context_for(rules, "放下青蛙", "drop", "action")
    dropped = pickup(ctx).model_copy(
        update={
            "method": ActionMethod(family="drop", description="放下青蛙"),
            "success_effects": (
                MoveEntityEffect(entity_id="dream_frog_item", location_id=ctx.player_view.scene.id),
            ),
        }
    )
    await engine.submit(
        SubmitAdjudicationRequest(room_id="companions", player_id="player", adjudication=dropped)
    )
    after = await context_for(rules, "查看随身物品")
    assert not any(i.id == "dream_frog_item" for i in after.player_view.inventory)
    assert any(i.id == "dream_frog_item" for i in after.player_view.scene.loose_items)


@pytest.mark.parametrize(
    "extra", ["check", "rule", "companion", "unknown", "other_destination", "failure", "action"]
)
async def test_same_location_guard_preserves_other_work(extra):
    _, rules, _ = await make_runtime()
    ctx = await context_for(rules, "前往别墅一层大厅")
    proposal = travel(ctx, "resort_reception")
    changes = {
        "check": {
            "check": RequiredAdjudicationCheck(
                candidates=(
                    SkillCheckCandidate(
                        candidate_id="test",
                        skill_id="stealth",
                        difficulty="regular",
                        method_summary="检定",
                        player_safe_reason="存在障碍",
                    ),
                )
            )
        },
        "rule": {"rule_decision": RuleDecisionRef(rule_id="rule", option_id="option")},
        "companion": {
            "success_effects": (
                *proposal.success_effects,
                ChangeEntityStateEffect(entity_id="james", key="accompanying", value=True),
            )
        },
        "unknown": {"success_effects": (NarrativeOnlyEffect(),)},
        "other_destination": {
            "success_effects": (EnterLocationEffect(location_id="guest_corridor"),)
        },
        "failure": {"failure_effects": (NarrativeOnlyEffect(),)},
        "action": {"method": ActionMethod(family="action", description="留在原地")},
    }
    assert (
        satisfied_travel_adjudication(
            ctx.step, ctx.player_view, proposal.model_copy(update=changes[extra])
        )
        is None
    )


@pytest.mark.parametrize(
    "path,expected", [(["hall"], False), (["pond", "hall"], True), (None, True)]
)
def test_memory_materializes_only_real_arrivals(path, expected):
    event = SimpleNamespace(
        type="travel.resolved",
        payload={"destination_id": "hall", "path": path},
        actor_id="actor",
        event_id="evt",
        room_id="room",
        visibility="public",
        sequence=1,
    )
    memory = _memory_from_game_event(cast(GameEvent, event))
    assert (memory is not None) is expected
    if memory:
        assert memory.kind == "visit"


@pytest.mark.parametrize("roll,success", [(20, True), (90, False)])
async def test_capture_waits_for_check_and_only_success_gets_inventory(roll, success):
    store, rules, _ = await make_runtime("frog_pond")
    engine = AdjudicationEngineService(store, dice=DiceRoller(SequenceDiceSource([roll])))
    ctx = await context_for(rules, "尝试抓稳一只青蛙", "capture", "action")
    proposal = pickup(ctx).model_copy(
        update={
            "check": RequiredAdjudicationCheck(
                candidates=(
                    SkillCheckCandidate(
                        candidate_id="capture",
                        skill_id="STR",
                        difficulty="regular",
                        method_summary="尝试抓稳",
                        player_safe_reason="需要抓稳才能携带",
                    ),
                )
            ),
            "failure_effects": (NarrativeOnlyEffect(),),
        }
    )
    execution = await engine.submit(
        SubmitAdjudicationRequest(room_id="companions", player_id="player", adjudication=proposal)
    )
    pending = execution.pending_decision
    assert pending is not None
    assert (
        store.inspect_state("companions").item_instances["dream_frog_item"].custody.kind
        == "location"
    )
    rolled = await engine.decide(
        CheckDecisionRequest(
            request_id="select",
            room_id="companions",
            player_id="player",
            source_revision=execution.view_revision,
            decision_id=pending.decision_id,
            decision_version=pending.decision_version,
            choice=SelectCheckChoice(candidate_id="capture"),
        )
    )
    if rolled.status == "awaiting_post_roll_decision":
        check = rolled.check_run
        assert check is not None
        option = next(
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
                option_id=option.option_id,
            )
        )
    assert rolled.outcome == ("success" if success else "failure")
    item = store.inspect_state("companions").item_instances["dream_frog_item"]
    assert item.custody.kind == ("actor_inventory" if success else "location")
    assert (await context_for(rules, "查看随身物品")).player_view.scene.id == "frog_pond"


async def test_already_here_continues_into_following_observation():
    store, rules, engine = await make_runtime()
    planned = plan(("travel", "前往别墅一层大厅"), ("action", "查看大厅周围"))

    def decide(ctx):
        proposal = travel(ctx, "resort_reception")
        if ctx.step_index == 0:
            return proposal
        return proposal.model_copy(
            update={
                "method": ActionMethod(family="observe", description="查看大厅周围"),
                "persistence_intent": "none",
                "success_effects": (NarrativeOnlyEffect(),),
            }
        )

    client = PlanClient(planned, decide)
    result = await start(application(store, rules, engine, client), planned)
    assert result.status == "awaiting_narration"
    assert len(client.steps) == 2
    assert len(client.narrations) == 1
    assert result.narration.text == "你查看了周围。"


async def test_unknown_destination_anchor_cannot_become_already_here():
    store, rules, engine = await make_runtime()
    planned = plan(("travel", "前往不存在的星空之城"))

    def decide(ctx):
        return travel(ctx, "resort_reception").model_copy(
            update={
                "persistence_intent": "none",
                "success_effects": (NarrativeOnlyEffect(),),
            }
        )

    client = PlanClient(planned, decide)
    app = application(store, rules, engine, client)
    before = len(store.inspect_domain_events("companions"))
    result = await start(app, planned)
    assert result.status == "needs_clarification"
    assert result.narration is not None
    assert "你已经在" not in result.narration.text
    run = await app.get_plan("companions", "test")
    assert run is not None and run.steps[0].already_at_destination_id is None
    assert not any(
        e.type.startswith("travel.") for e in store.inspect_domain_events("companions")[before:]
    )


@pytest.mark.parametrize("goal", ["我要去吃饭", "前往不存在的星空之城"])
async def test_fake_unknown_travel_does_not_confirm_current_location(goal):
    store, rules, engine = await make_runtime()
    app = build_action_plan_turn_application(
        store=store,
        engine=rules,
        adjudication_engine=engine,
        settings=Settings(host_model_provider="fake"),
        memory_source=EmptyMemory(),
    )
    before = len(store.inspect_domain_events("companions"))
    result = await app.start(
        room_id="companions", player_id="player", client_action_id="test", utterance=goal
    )

    assert result.status == "needs_clarification"
    assert result.narration is not None
    assert "已经在" not in result.narration.text
    run = await app.get_plan("companions", "test")
    assert run is not None
    assert run.steps[0].already_at_destination_id is None
    assert run.steps[0].safe_failure_code == "TRAVEL_DESTINATION_NOT_FOUND"
    assert len(store.inspect_domain_events("companions")) == before
