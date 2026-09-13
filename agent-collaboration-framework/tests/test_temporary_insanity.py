"""Single-loss insanity is an Engine consequence, not a narrated assertion."""

from tests.sanity_fixtures import ACTOR, ROOM, make_store, settle


async def test_five_point_loss_requires_int_before_parent_can_resume():
    store = make_store()
    result = await settle(store, dice=(5,))
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 55
    assert result.pending_decision is not None
    assert result.pending_decision.options[0].skill_id == "INT"
    assert len(store.inspect_state(ROOM).rule_agendas) == 1


async def resolve_int(store, execution, *, roll=21, dice=(8, 3, 2), tag="int"):
    from collaboration_framework.contracts import (
        CheckDecisionRequest,
        SelectCheckChoice,
        PostRollDecisionRequest,
    )
    from collaboration_framework.engine import (
        AdjudicationEngineService,
        DiceRoller,
        SequenceDiceSource,
    )
    from tests.sanity_fixtures import PLAYER

    pending = execution.pending_decision
    assert pending is not None
    rolled = await AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource([roll]))
    ).decide(
        CheckDecisionRequest(
            room_id=ROOM,
            player_id=PLAYER,
            request_id=tag + "-roll",
            source_revision=execution.view_revision,
            decision_id=pending.decision_id,
            decision_version=pending.decision_version,
            choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
        )
    )
    check = rolled.check_run
    assert check is not None
    assert [option.kind for option in check.post_roll_options] == ["accept_result"]
    request = PostRollDecisionRequest(
        room_id=ROOM,
        player_id=PLAYER,
        request_id=tag + "-accept",
        source_revision=rolled.view_revision,
        check_id=check.check_id,
        check_version=check.version,
        option_id="accept-current",
    )
    result = await AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource(dice))
    ).decide_post_roll(request)
    return result, request


async def test_int_success_applies_independent_condition_and_bout_once():
    from collaboration_framework.engine import (
        AdjudicationEngineService,
        DiceRoller,
        SequenceDiceSource,
        GameState,
    )

    store = make_store()
    pending = await settle(store, dice=(5,))
    result, request = await resolve_int(store, pending)
    state = store.inspect_state(ROOM)
    actor = state.actors[ACTOR]
    assert actor.resources.san == 55
    assert set(actor.conditions) == {"temporary_insanity", "madness_bout"}
    temp, bout = (
        next(c for c in actor.condition_states if c.condition_id == kind)
        for kind in ("temporary_insanity", "madness_bout")
    )
    assert temp.expiry.absolute_hour == 20
    assert bout.expiry.absolute_hour == 14
    assert actor.sanity.bouts[0].type_id == "battered"
    assert not state.time_tasks
    assert not state.time_occurrences
    assert GameState.model_validate_json(state.model_dump_json()) == state
    assert not state.rule_agendas
    facts = [
        e
        for e in store.inspect_domain_events(ROOM)
        if e.type == "actor.temporary_insanity"
    ]
    assert len(facts) == 1
    replay = await AdjudicationEngineService(
        store, dice=DiceRoller(SequenceDiceSource([]))
    ).decide_post_roll(request)
    assert replay.event_refs == result.event_refs
    assert len(store.inspect_state(ROOM).actors[ACTOR].sanity.bouts) == 1


async def test_int_failure_keeps_loss_without_insanity():
    store = make_store()
    pending = await settle(store, dice=(5,))
    result, _ = await resolve_int(store, pending, roll=91, dice=())
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 55
    assert actor.conditions == ()
    assert result.status == "resolved"
    assert not store.inspect_state(ROOM).time_tasks


async def test_below_threshold_and_zero_loss_do_not_require_int():
    for loss in (0, 4):
        store = make_store()
        result = await settle(
            store, dice=(loss,) if loss else (), roll=81 if loss else 1
        )
        assert result.pending_decision is None
        assert store.inspect_state(ROOM).actors[ACTOR].conditions == ()


async def advance_time(store, tag, *, consent=False):
    from collaboration_framework.contracts import (
        AdvanceWorldTimeEffect,
        ActionTarget,
        ActionMethod,
    )
    from collaboration_framework.engine import AdjudicationEngineService
    from tests.sanity_fixtures import trigger

    async with store.transaction(ROOM) as tx:
        runtime = await tx.load_runtime()
    request = trigger(runtime.revision, tag)
    action = request.adjudication.model_copy(
        update={
            "target": ActionTarget(kind="location", id=runtime.game_state.scene_id),
            "method": ActionMethod(family="rest", description="等待时间推进"),
            "success_effects": (AdvanceWorldTimeEffect(),),
        }
    )
    command = request.model_copy(update={"adjudication": action})
    if consent:
        return await AdjudicationEngineService(store).submit_with_time_consent(
            command,
            consent_player_ids=tuple(
                sorted({a.player_id for a in runtime.game_state.actors.values()})
            ),
        )
    return await AdjudicationEngineService(store).submit(command)


async def test_bout_and_temporary_insanity_expire_at_normal_time_points():
    store = make_store()
    pending = await settle(store, dice=(5,))
    await resolve_int(store, pending)
    await advance_time(store, "evening")
    state = store.inspect_state(ROOM)
    assert state.world_time.current.absolute_hour == 18
    assert state.actors[ACTOR].conditions == ("temporary_insanity",)
    await advance_time(store, "next-morning")
    state = store.inspect_state(ROOM)
    assert state.world_time.current.absolute_hour == 30
    assert state.actors[ACTOR].conditions == ()
    assert not state.time_tasks
    ended = [
        e
        for e in store.inspect_domain_events(ROOM)
        if e.type == "actor.condition_removed"
    ]
    assert [e.payload["condition_id"] for e in ended] == [
        "madness_bout",
        "temporary_insanity",
    ]


async def test_bout_immunity_then_underlying_stimulus_starts_one_new_bout():
    store = make_store()
    pending = await settle(store, dice=(5,))
    await resolve_int(store, pending)
    during = await settle(store, dice=(4,), request_id="during-bout")
    assert during.pending_decision is None
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 55
    await advance_time(store, "bout-end")
    after = await settle(store, dice=(1, 2, 1), request_id="new-stimulus")
    assert after.pending_decision is None
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 54
    assert len(actor.sanity.bouts) == 2
    assert set(actor.conditions) == {"temporary_insanity", "madness_bout"}
    assert (
        next(
            c for c in actor.condition_states if c.condition_id == "temporary_insanity"
        ).expiry.absolute_hour
        == 20
    )


async def test_round_based_bout_is_explicitly_unsupported_and_loss_is_not_repeated():
    import pytest
    from collaboration_framework.contracts import ContractError
    from collaboration_framework.contracts.sanity import SanityPolicy
    from tests.sanity_fixtures import sandbox_content

    content = sandbox_content().model_copy(
        update={"sanity_policy": SanityPolicy(bout_mode="rounds")}
    )
    store = make_store(content)
    pending = await settle(store, dice=(5,))
    with pytest.raises(ContractError, match="INSANITY_ROUNDS_UNSUPPORTED"):
        await resolve_int(store, pending)
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 55
    assert len(actor.sanity.losses) == 1
    assert not actor.conditions
    assert not store.inspect_state(ROOM).time_tasks


async def test_condition_can_outlast_story_terminal_without_rejecting_san_result():
    from tests.sanity_fixtures import sandbox_content

    payload = sandbox_content().to_json_dict()
    payload["time_policy"]["terminal_point"] = {"point_id": "hour_18", "day_index": 0}
    content = sandbox_content().__class__.model_validate(payload)
    store = make_store(content)
    pending = await settle(store, dice=(5,))
    result, _ = await resolve_int(store, pending, dice=(8, 3, 2))
    assert result.status == "resolved"
    await advance_time(store, "terminal")
    state = store.inspect_state(ROOM)
    assert state.world_time.current.absolute_hour == 18
    assert state.actors[ACTOR].resources.san == 55
    assert state.actors[ACTOR].conditions == ("temporary_insanity",)
    assert not state.time_tasks


async def test_real_paper_chase_rule_consumes_engine_generated_insanity_event():
    from collaboration_framework.engine import InMemoryEngineStore
    from tests.test_projection_v3 import module

    content = module()
    state = make_store(content).inspect_state(ROOM)
    state = state.model_copy(
        update={
            "world_time": state.world_time.model_copy(
                update={
                    "current_point_id": "hour_06",
                    "current": state.world_time.current.model_copy(
                        update={"hour_of_day": 6}
                    ),
                }
            )
        }
    )
    state.entities["ghoul_crowd"] = {"revealed": True}
    state.entities["case_tracker"] = {
        "crowd_sight_resolved": False,
        "first_ghoul_sight_resolved": True,
        "sent_to_asylum": False,
    }
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    pending = await settle(store, dice=(5,))
    result, _ = await resolve_int(store, pending)
    state = store.inspect_state(ROOM)
    assert state.entities["case_tracker"]["sent_to_asylum"] is True
    assert "unconscious" in state.actors[ACTOR].conditions
    assert "temporary_insanity" in state.actors[ACTOR].conditions
    assert (
        sum(
            e.type == "actor.temporary_insanity"
            for e in store.inspect_domain_events(ROOM)
        )
        == 1
    )
    assert any(
        r.state_key == "condition:temporary_insanity" for r in result.committed_results
    )
    await advance_time(store, "real-bout-end")
    assert "unconscious" in store.inspect_state(ROOM).actors[ACTOR].conditions
    await advance_time(store, "real-temporary-end")
    assert store.inspect_state(ROOM).actors[ACTOR].conditions == ("unconscious",)


async def test_active_condition_projection_has_relative_time_without_hidden_source():
    from collaboration_framework.engine.projection_v3 import project_v3
    from tests.sanity_fixtures import PLAYER

    store = make_store()
    pending = await settle(store, dice=(5,))
    await resolve_int(store, pending)
    async with store.transaction(ROOM) as tx:
        runtime = await tx.load_runtime()
    snapshot = project_v3(runtime, player_id=PLAYER, actor_id=ACTOR)
    details = snapshot.self_actor.condition_details
    assert {c.name: c.remaining_hours for c in details} == {
        "临时疯狂": 8,
        "疯狂发作": 2,
    }
    payload = [c.to_json_dict() for c in details]
    assert not any(
        "source" in c or "absolute_hour" in c or "reference_id" in c for c in payload
    )


async def test_required_int_blocks_new_actor_action():
    import pytest
    from collaboration_framework.contracts import ContractError

    store = make_store()
    await settle(store, dice=(5,))
    with pytest.raises(ContractError, match="CHECK_CONSEQUENCE_PENDING"):
        await advance_time(store, "skip-int")
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 55


async def test_safe_rest_clears_temporary_state_before_deadlines():
    from tests.sanity_fixtures import (
        sandbox_content,
        with_world_actions,
        invoke_world_action,
    )

    content = with_world_actions(
        sandbox_content(),
        {
            "sleep": (
                "coc7.safe_rest",
                {"rest_id": "safe-night-1", "safe": True, "uninterrupted": True},
            )
        },
    )
    store = make_store(content)
    pending = await settle(store, dice=(5,))
    await resolve_int(store, pending)
    result = await invoke_world_action(store, "sleep")
    assert result.status == "resolved"
    state = store.inspect_state(ROOM)
    assert state.actors[ACTOR].conditions == ()
    assert state.actors[ACTOR].resources.san == 55
    assert not state.time_tasks
    assert (
        sum(
            e.type == "actor.condition_removed"
            for e in store.inspect_domain_events(ROOM)
        )
        == 2
    )
    await invoke_world_action(store, "sleep", tag="repeat-sleep")
    assert (
        sum(
            e.type == "actor.condition_removed"
            for e in store.inspect_domain_events(ROOM)
        )
        == 2
    )


async def test_authored_daily_expiry_is_bound_to_next_day_once():
    from collaboration_framework.engine import InMemoryEngineStore
    from tests.sanity_fixtures import (
        sandbox_content,
        with_world_actions,
        invoke_world_action,
    )

    content = with_world_actions(
        sandbox_content(),
        {
            "apply": (
                "coc7.apply_condition",
                {
                    "condition": "unconscious",
                    "expiry": {"kind": "time_point", "reference_id": "hour_18"},
                },
            )
        },
    )
    state = make_store(content).inspect_state(ROOM)
    state = state.model_copy(
        update={
            "world_time": state.world_time.model_copy(
                update={
                    "current_point_id": "hour_18",
                    "current": state.world_time.current.model_copy(
                        update={"hour_of_day": 18}
                    ),
                }
            )
        }
    )
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    await invoke_world_action(store, "apply")
    condition = store.inspect_state(ROOM).actors[ACTOR].condition_states[0]
    assert condition.expiry.absolute_hour == 42
    for name in ("next-morning", "next-noon"):
        await advance_time(store, name)
        assert store.inspect_state(ROOM).actors[ACTOR].conditions == ("unconscious",)
    await advance_time(store, "next-night")
    assert store.inspect_state(ROOM).actors[ACTOR].conditions == ()
