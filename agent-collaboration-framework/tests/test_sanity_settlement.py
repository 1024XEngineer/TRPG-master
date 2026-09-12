import pytest
from collaboration_framework.engine import (
    AdjudicationEngineService,
    DiceRoller,
    SequenceDiceSource,
)
from collaboration_framework.contracts import ContractError, PushAdjudication
from tests.sanity_fixtures import (
    PLAYER,
    ACTOR,
    ROOM,
    make_store,
    sandbox_content,
    roll_sanity,
    settle,
)


@pytest.mark.parametrize(
    "roll,loss,expected",
    [(1, 0, 60), (10, 0, 60), (20, 0, 60), (50, 0, 60), (81, 4, 56), (100, 4, 56)],
)
async def test_six_degrees_use_the_declared_loss(roll, loss, expected):
    store = make_store()
    request = await roll_sanity(store, roll=roll)
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 60
    assert not any(
        e.type == "actor.sanity_loss" for e in store.inspect_domain_events(ROOM)
    )
    engine = AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource([loss] if loss else []))
    )
    result = await engine.decide_post_roll(request)
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == expected
    facts = [
        e for e in store.inspect_domain_events(ROOM) if e.type == "actor.sanity_loss"
    ]
    assert len(facts) == 1
    assert facts[0].payload["after"] == expected
    assert result.committed_results[-1].state_value == expected
    replay = await AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource([]))
    ).decide_post_roll(request)
    assert replay.event_refs == result.event_refs
    with pytest.raises(ContractError):
        await engine.decide_post_roll(
            request.model_copy(
                update={
                    "request_id": "different",
                    "source_revision": result.view_revision,
                }
            )
        )
    assert (
        len(
            [
                e
                for e in store.inspect_domain_events(ROOM)
                if e.type == "actor.sanity_loss"
            ]
        )
        == 1
    )


async def test_zero_floor_keeps_requested_and_actual_loss():
    store = make_store(san=2)
    await settle(store)
    fact = next(
        e for e in store.inspect_domain_events(ROOM) if e.type == "actor.sanity_loss"
    )
    assert (
        fact.payload["before"],
        fact.payload["requested_delta"],
        fact.payload["actual_delta"],
        fact.payload["after"],
    ) == (2, -4, -2, 0)


async def test_success_fixed_loss():
    store = make_store(
        sandbox_content(parameters={"success_loss": "1", "failure_loss": "1d3"})
    )
    await settle(store, dice=(), roll=20)
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 59


@pytest.mark.parametrize(
    "bad", [None, True, -1, "1d6+POW/5", "0d6", "1d1", {"value": 1}]
)
async def test_bad_parameters_leave_pending_check_and_resource_intact(bad):
    store = make_store(
        sandbox_content(parameters={"success_loss": "0", "failure_loss": bad})
    )
    request = await roll_sanity(store)
    with pytest.raises((ValueError, ContractError)):
        await AdjudicationEngineService(
            store, dice=DiceRoller(SequenceDiceSource([]))
        ).decide_post_roll(request)
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 60
    assert not any(
        e.type == "actor.sanity_loss" for e in store.inspect_domain_events(ROOM)
    )


async def test_active_rule_sanity_uses_same_settlement_without_agenda():
    from collaboration_framework.contracts import (
        RuleSpecV3,
        RuleDecisionRef,
        RequiredAdjudicationCheck,
        SkillCheckCandidate,
        CheckDecisionRequest,
        SelectCheckChoice,
        PostRollDecisionRequest,
    )
    from tests.sanity_fixtures import trigger

    content = sandbox_content()
    rule = content.rules[0].to_json_dict()
    rule["trigger"] = {
        "kind": "agent_match",
        "scope": {"action_families": ["observe"], "target_ids": ["cemetery_figure"]},
        "question": {"kind": "action_declaration", "semantic_hints": ["观察真容"]},
        "options": [{"id": "default", "semantic_hints": ["观察"]}],
    }
    rule["execution"]["steps"][0]["check"]["initiation_kind"] = "active_action"
    content = content.model_copy(update={"rules": (RuleSpecV3.model_validate(rule),)})
    store = make_store(content)
    original = trigger("0")
    request = original.model_copy(
        update={
            "adjudication": original.adjudication.model_copy(
                update={
                    "rule_decision": RuleDecisionRef(
                        rule_id="test_sanity", option_id="default"
                    ),
                    "success_effects": (),
                    "check": RequiredAdjudicationCheck(
                        candidates=(
                            SkillCheckCandidate(
                                candidate_id="san",
                                skill_id="san",
                                difficulty="regular",
                                method_summary="观察",
                                player_safe_reason="理智检定",
                            ),
                        )
                    ),
                }
            )
        }
    )
    engine = AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource([81, 4]))
    )
    result = await engine.submit(request)
    pending = result.pending_decision
    assert pending is not None
    result = await engine.decide(
        CheckDecisionRequest(
            room_id=ROOM,
            player_id=PLAYER,
            request_id="active-roll",
            source_revision=result.view_revision,
            decision_id=pending.decision_id,
            decision_version=pending.decision_version,
            choice=SelectCheckChoice(candidate_id="san"),
        )
    )
    run = result.check_run
    assert run is not None
    result = await engine.decide_post_roll(
        PostRollDecisionRequest(
            room_id=ROOM,
            player_id=PLAYER,
            request_id="active-accept",
            source_revision=result.view_revision,
            check_id=run.check_id,
            check_version=run.version,
            option_id="accept-current",
        )
    )
    assert result.status == "resolved"
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 56
    assert store.inspect_state(ROOM).rule_agendas == {}


@pytest.mark.parametrize(
    "choice,dice,expected",
    [("spend-luck-21", (), 60), ("push-once", (20,), 60), ("push-once", (81, 4), 56)],
)
async def test_final_postroll_outcome_alone_determines_loss(choice, dice, expected):
    store = make_store()
    request = await roll_sanity(store)
    result = await AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource(dice))
    ).decide_post_roll(
        request.model_copy(
            update={
                "option_id": choice,
                "push_adjudication": PushAdjudication(method_description="重新集中精神")
                if choice == "push-once"
                else None,
            }
        )
    )
    assert result.status == "resolved"
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == expected
    assert (
        len(
            [
                e
                for e in store.inspect_domain_events(ROOM)
                if e.type == "actor.sanity_loss"
            ]
        )
        == 1
    )


@pytest.mark.parametrize("index", range(6))
@pytest.mark.parametrize("roll", [20, 81])
async def test_published_sanity_parameters_have_executable_success_and_failure(
    index, roll
):
    import json
    from pathlib import Path

    modules = (
        Path(__file__).resolve().parents[1]
        / "docs/module-parser/examples/module-content-validation"
    )
    specs = []
    for folder in ["追书人", "银之锁", "常暗之厢"]:
        for rule in json.loads(
            (modules / folder / "module-content-v3.json").read_text()
        )["rules"]:
            for step in rule["execution"]["steps"]:
                if step.get("check", {}).get("profile_id") == "coc7.sanity":
                    specs.append(step["check"])
    assert len(specs) == 6
    params = specs[index]["parameters"]
    store = make_store(sandbox_content(parameters=params))
    await settle(store, roll=roll, dice=(2,))
    loss = int(params["success_loss"]) if roll == 20 else 2
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 60 - loss
