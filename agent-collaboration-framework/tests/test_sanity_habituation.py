"""Actor/source habituation through repeated formal rule checks."""

from tests.sanity_fixtures import ACTOR, ROOM, make_store, sandbox_content, settle


async def test_same_source_losses_are_limited_before_write():
    content = sandbox_content(
        parameters={"success_loss": "0", "failure_loss": "1d6", "habit_cap": 6}
    )
    store = make_store(content)
    for i, loss in enumerate((4, 4, 3)):
        await settle(store, dice=(loss,), request_id=f"encounter-{i}")
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 54

    ledger = store.inspect_state(ROOM).actors[ACTOR].sanity
    assert ledger.habituation["test.creature"] == 6
    assert [loss.requested for loss in ledger.losses] == [4, 4, 3]
    assert [loss.actual for loss in ledger.losses] == [4, 2, 0]
    assert [loss.after for loss in ledger.losses] == [56, 54, 54]
    facts = [
        e for e in store.inspect_domain_events(ROOM) if e.type == "actor.sanity_loss"
    ]
    assert len(facts) == 3
    assert all(e.visibility == "hidden" for e in facts)


async def test_actual_loss_floor_and_independent_actor_ledgers():
    from collaboration_framework.engine import InMemoryEngineStore

    content = sandbox_content(
        parameters={"success_loss": "0", "failure_loss": "1d6", "habit_cap": 6}
    )
    original = make_store(content, san=1)
    state = original.inspect_state(ROOM)
    state.actors["other"] = state.actors[ACTOR].model_copy(
        update={"player_id": "other-player"}
    )
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    await settle(store)
    after = store.inspect_state(ROOM)
    assert after.actors[ACTOR].resources.san == 0
    assert after.actors[ACTOR].sanity.habituation["test.creature"] == 1
    assert after.actors["other"].resources.san == 1
    assert after.actors["other"].sanity.losses == ()


async def test_canonical_loss_deduplicates_resource_alias_and_history():
    from collaboration_framework.contracts.sanity import SanityLedger
    from collaboration_framework.registry.sanity_ledger import append_loss

    store = make_store(
        sandbox_content(
            parameters={"success_loss": "0", "failure_loss": "1d6", "habit_cap": 6}
        )
    )
    await settle(store)
    ledger = SanityLedger()
    events = store.inspect_domain_events(ROOM)
    for event in (*events, *reversed(events)):
        ledger = append_loss(ledger, event)
    assert ledger.habituation == {"test.creature": 4}
    assert len(ledger.losses) == 1


async def test_old_snapshot_backfills_once_from_canonical_facts():
    from dataclasses import replace

    store = make_store(
        sandbox_content(
            parameters={"success_loss": "0", "failure_loss": "1d6", "habit_cap": 6}
        )
    )
    await settle(store)
    record = store._rooms[ROOM]
    state = store.inspect_state(ROOM)
    state.actors[ACTOR] = state.actors[ACTOR].model_copy(update={"sanity": None})
    record.data = replace(record.data, game_state=state)
    await settle(store, request_id="after-upgrade")
    ledger = store.inspect_state(ROOM).actors[ACTOR].sanity
    assert ledger.coverage == "canonical_history"
    assert ledger.habituation == {"test.creature": 6}
    assert len(ledger.losses) == 2
    await settle(store, request_id="after-restart")
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 54


async def test_development_phase_decays_once_without_refund():
    from collaboration_framework.contracts import RuleSpecV3
    from collaboration_framework.engine import AdjudicationEngineService
    from tests.sanity_fixtures import trigger

    content = sandbox_content(
        parameters={"success_loss": "0", "failure_loss": "1d6", "habit_cap": 6}
    )
    phase = content.rules[0].to_json_dict()
    phase["id"] = "development"
    phase["trigger"]["when"]["args"]["value"] = False
    phase["execution"] = {
        "branches": [{"id": "default", "entry_step_id": "develop"}],
        "steps": [
            {
                "id": "develop",
                "kind": "invoke_ruleset_action",
                "action_id": "coc7.investigator_development",
                "actor_binding": "actor",
                "parameters": {"phase_id": "chapter-1"},
                "next_step_id": "finish",
            },
            {"id": "finish", "kind": "finish"},
        ],
    }
    content = content.model_copy(
        update={"rules": (*content.rules, RuleSpecV3.model_validate(phase))}
    )
    store = make_store(content)
    await settle(store, dice=(4,))
    for i in range(2):
        async with store.transaction(ROOM) as tx:
            runtime = await tx.load_runtime()
        request = trigger(runtime.revision, f"rest-{i}")
        effect = request.adjudication.success_effects[0].model_copy(
            update={"value": False}
        )
        request = request.model_copy(
            update={
                "adjudication": request.adjudication.model_copy(
                    update={"success_effects": (effect,)}
                )
            }
        )
        await AdjudicationEngineService(store).submit(request)
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 56
    assert actor.sanity.habituation == {"test.creature": 3}
    assert actor.sanity.development_phases == ("chapter-1",)
    await settle(store, dice=(4,), request_id="next-encounter")
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 53


async def test_new_source_has_its_own_cap():
    from collaboration_framework.contracts import (
        RuleSpecV3,
        CheckDecisionRequest,
        PostRollDecisionRequest,
        SelectCheckChoice,
    )
    from collaboration_framework.contracts.sanity import SanitySource
    from collaboration_framework.engine import (
        AdjudicationEngineService,
        DiceRoller,
        SequenceDiceSource,
    )
    from tests.sanity_fixtures import trigger, PLAYER

    content = sandbox_content(
        parameters={"success_loss": "0", "failure_loss": "1d6", "habit_cap": 6}
    )
    other = content.rules[0].to_json_dict()
    other["id"] = "other_source"
    other["trigger"]["when"]["args"]["value"] = False
    other["execution"]["steps"][0]["check"]["parameters"] = {
        "success_loss": "0",
        "failure_loss": "2",
        "sanity_source": "test.other",
    }
    content = content.model_copy(
        update={
            "rules": (*content.rules, RuleSpecV3.model_validate(other)),
            "sanity_sources": (
                *content.sanity_sources,
                SanitySource(id="test.other", habit_cap=6),
            ),
        }
    )
    store = make_store(content)
    await settle(store, dice=(4,), request_id="source-a-1")
    await settle(store, dice=(4,), request_id="source-a-2")
    async with store.transaction(ROOM) as tx:
        runtime = await tx.load_runtime()
    request = trigger(runtime.revision, "source-b")
    effect = request.adjudication.success_effects[0].model_copy(update={"value": False})
    request = request.model_copy(
        update={
            "adjudication": request.adjudication.model_copy(
                update={"success_effects": (effect,)}
            )
        }
    )
    service = AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource([81]))
    )
    result = await service.submit(request)
    pending = result.pending_decision
    result = await service.decide(
        CheckDecisionRequest(
            room_id=ROOM,
            player_id=PLAYER,
            request_id="b-roll",
            source_revision=result.view_revision,
            decision_id=pending.decision_id,
            decision_version=pending.decision_version,
            choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
        )
    )
    check = result.check_run
    await service.decide_post_roll(
        PostRollDecisionRequest(
            room_id=ROOM,
            player_id=PLAYER,
            request_id="b-accept",
            source_revision=result.view_revision,
            check_id=check.check_id,
            check_version=check.version,
            option_id="accept-current",
        )
    )
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 52
    assert actor.sanity.habituation == {"test.creature": 6, "test.other": 2}


def test_unknown_source_and_cap_conflicts_are_rejected_at_publication():
    from collaboration_framework.module import validate_module_v3
    from collaboration_framework.contracts import ModuleContentV3

    content = sandbox_content(
        parameters={"success_loss": "0", "failure_loss": "1d6", "habit_cap": 6}
    )
    payload = content.to_json_dict()
    payload["sanity_sources"] = []
    report = validate_module_v3(ModuleContentV3.model_validate(payload))
    assert any(issue.code == "SANITY_SOURCE_UNKNOWN" for issue in report.errors)
    payload = content.to_json_dict()
    payload["sanity_sources"][0]["habit_cap"] = 5
    report = validate_module_v3(ModuleContentV3.model_validate(payload))
    assert any(issue.code == "SANITY_CAP_CONFLICT" for issue in report.errors)


async def test_unproven_old_history_requires_an_explicit_baseline():
    import pytest
    from collaboration_framework.contracts import ContractError
    from collaboration_framework.engine import InMemoryEngineStore

    content = sandbox_content(
        parameters={"success_loss": "0", "failure_loss": "1d6", "habit_cap": 6}
    )
    state = make_store(content).inspect_state(ROOM)
    state = state.model_copy(update={"event_sequence": 30})
    state.actors[ACTOR] = state.actors[ACTOR].model_copy(update={"sanity": None})
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    with pytest.raises(ContractError, match="SANITY_HISTORY_CONFIRMATION_REQUIRED"):
        await settle(store)
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 60
    assert not any(
        e.type == "actor.sanity_loss" for e in store.inspect_domain_events(ROOM)
    )


async def test_explicit_history_confirmation_executes_then_preserves_the_declared_cap():
    from collaboration_framework.engine import InMemoryEngineStore
    from tests.sanity_fixtures import with_world_actions, invoke_world_action

    content = with_world_actions(
        sandbox_content(
            parameters={"success_loss": "0", "failure_loss": "1d6", "habit_cap": 6}
        ),
        {
            "confirm": (
                "coc7.acknowledge_sanity_history",
                {
                    "cutover_id": "known-session-history",
                    "reason": "Keeper supplied prior loss",
                    "habituation": {"test.creature": 5},
                },
            )
        },
    )
    state = (
        make_store(content)
        .inspect_state(ROOM)
        .model_copy(update={"event_sequence": 30})
    )
    state.actors[ACTOR] = state.actors[ACTOR].model_copy(update={"sanity": None})
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    result = await invoke_world_action(store, "confirm")
    assert result.status == "resolved"
    await settle(store, dice=(4,), request_id="after-confirmation")
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 59
    assert actor.sanity.habituation == {"test.creature": 6}
    await invoke_world_action(store, "confirm", tag="repeat-confirmation")
    assert store.inspect_state(ROOM).actors[ACTOR].sanity.habituation == {
        "test.creature": 6
    }
    assert (
        sum(
            e.type == "actor.sanity_history_confirmed"
            for e in store.inspect_domain_events(ROOM)
        )
        == 1
    )
