"""Cumulative loss uses a stable game-period baseline and actual loss facts."""

from tests.sanity_fixtures import ACTOR, ROOM, make_store, settle


async def test_small_losses_reach_one_fifth_without_an_int_check():
    store = make_store()
    for i, loss in enumerate((4, 4, 3)):
        result = await settle(store, dice=(loss,), request_id=f"loss-{i}")
        assert result.pending_decision is None
        assert (
            "indefinite_insanity"
            not in store.inspect_state(ROOM).actors[ACTOR].conditions
        )
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 49
    result = await settle(store, dice=(1, 3, 2), request_id="threshold")
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 48
    assert "indefinite_insanity" in actor.conditions
    assert result.pending_decision is None


async def cross_threshold(store, tag="loss"):
    for i, loss in enumerate((4, 4, 3, 1)):
        result = await settle(
            store, dice=(loss, 3, 2) if i == 3 else (loss,), request_id=f"{tag}-{i}"
        )
    return result


async def advance_until(store, absolute, tag="time"):
    from tests.test_temporary_insanity import advance_time

    for i in range(1000):
        if store.inspect_state(ROOM).world_time.current.absolute_hour >= absolute:
            return
        await advance_time(
            store, f"{tag}-{i}", consent=len(store.inspect_state(ROOM).actors) > 1
        )
    raise AssertionError("world time did not reach the requested boundary")


async def test_simultaneous_single_and_cumulative_threshold_only_creates_indefinite():
    store = make_store()
    await settle(store, dice=(4,), request_id="one")
    await settle(store, dice=(3,), request_id="two")
    result = await settle(store, dice=(5, 2, 1), request_id="both")
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert result.pending_decision is None
    assert set(actor.conditions) == {"indefinite_insanity", "madness_bout"}
    assert len(actor.sanity.bouts) == 1
    events = store.inspect_domain_events(ROOM)
    assert sum(e.type == "actor.indefinite_insanity" for e in events) == 1
    assert not any(e.type == "actor.temporary_insanity" for e in events)


async def test_integer_one_fifth_keeps_fractional_threshold_and_san_zero_is_not_cured():
    store = make_store(san=59)
    for i, loss in enumerate((4, 4, 3)):
        await settle(store, dice=(loss,), request_id=f"low-{i}")
    assert store.inspect_state(ROOM).actors[ACTOR].conditions == ()
    await settle(store, dice=(1, 1, 1), request_id="twelve")
    assert "indefinite_insanity" in store.inspect_state(ROOM).actors[ACTOR].conditions
    zero = make_store(san=3)
    result = await settle(zero, dice=(4,))
    assert zero.inspect_state(ROOM).actors[ACTOR].resources.san == 0
    assert zero.inspect_state(ROOM).actors[ACTOR].conditions == ()
    assert result.pending_decision is None


async def test_san_gain_does_not_move_period_baseline():
    from collaboration_framework.contracts.resources import (
        ChangeActorResourceEffect,
        FixedQuantity,
    )
    from collaboration_framework.engine import AdjudicationEngineService
    from tests.sanity_fixtures import trigger

    store = make_store()
    await settle(store, dice=(4,), request_id="loss")
    async with store.transaction(ROOM) as tx:
        runtime = await tx.load_runtime()
    req = trigger(runtime.revision, "gain")
    req = req.model_copy(
        update={
            "adjudication": req.adjudication.model_copy(
                update={
                    "success_effects": (
                        ChangeActorResourceEffect(
                            resource_id="san",
                            direction="increase",
                            quantity=FixedQuantity(value=10),
                            reason_code="test.recovery",
                        ),
                    )
                }
            )
        }
    )
    await AdjudicationEngineService(store).submit(req)
    for i in range(2):
        await settle(store, dice=(4, 2, 1), request_id=f"more-{i}")
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 58
    assert actor.sanity.window.baseline_san == 60
    assert actor.sanity.window.loss_total == 12
    assert "indefinite_insanity" in actor.conditions


async def test_world_day_resets_actual_window_but_preserves_indefinite_insanity():
    from collaboration_framework.contracts.sanity import SanityPolicy
    from tests.sanity_fixtures import sandbox_content

    store = make_store(
        sandbox_content().model_copy(
            update={"sanity_policy": SanityPolicy(window_boundary="world_day")}
        )
    )
    await cross_threshold(store)
    await advance_until(store, 30)
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.conditions == ("indefinite_insanity",)
    assert actor.sanity.window.id == "day:1"
    assert actor.sanity.window.baseline_san == 48
    assert actor.sanity.window.loss_total == 0
    assert actor.sanity.previous_windows[0].loss_total == 12
    await settle(store, dice=(1, 1, 1), request_id="next-day")
    assert len(store.inspect_state(ROOM).actors[ACTOR].sanity.bouts) == 2
    assert (
        sum(
            e.type == "actor.indefinite_insanity"
            for e in store.inspect_domain_events(ROOM)
        )
        == 1
    )


async def test_default_window_waits_for_explicit_rest_and_rest_is_idempotent():
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
                {"rest_id": "night-1", "safe": True, "uninterrupted": True},
            )
        },
    )
    store = make_store(content)
    await settle(store, dice=(4,), request_id="first")
    await advance_until(store, 30)
    assert store.inspect_state(ROOM).actors[ACTOR].sanity.window.loss_total == 4
    await invoke_world_action(store, "sleep")
    await settle(store, dice=(3,), request_id="after-rest")
    await invoke_world_action(store, "sleep", tag="same-rest")
    ledger = store.inspect_state(ROOM).actors[ACTOR].sanity
    assert ledger.window.baseline_san == 56
    assert ledger.window.loss_total == 3
    assert len(ledger.previous_windows) == 1


async def test_habituation_actual_loss_is_the_only_cumulative_input():
    from tests.sanity_fixtures import sandbox_content

    store = make_store(
        sandbox_content(
            parameters={"success_loss": "0", "failure_loss": "1d6", "habit_cap": 6}
        )
    )
    for i in range(3):
        await settle(store, dice=(4,), request_id=f"habit-{i}")
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.sanity.window.loss_total == 6
    assert [loss.actual for loss in actor.sanity.losses] == [4, 2, 0]
    assert actor.conditions == ()


async def test_upgrade_cutover_is_explicit_and_late_old_fact_does_not_pollute_new_period():
    from collaboration_framework.engine import InMemoryEngineStore
    from collaboration_framework.registry.sanity_ledger import append_loss
    from tests.sanity_fixtures import (
        sandbox_content,
        with_world_actions,
        invoke_world_action,
    )

    content = with_world_actions(
        sandbox_content(),
        {
            "rest": (
                "coc7.safe_rest",
                {"rest_id": "new", "safe": True, "uninterrupted": True},
            )
        },
    )
    state = make_store(content).inspect_state(ROOM)
    actor = state.actors[ACTOR]
    state.actors[ACTOR] = actor.model_copy(
        update={"sanity": actor.sanity.model_copy(update={"window": None})}
    )
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    await settle(store, dice=(4,), request_id="upgrade")
    ledger = store.inspect_state(ROOM).actors[ACTOR].sanity
    assert ledger.window.coverage == "upgrade_cutover"
    assert "period_baseline_missing" in ledger.history_gaps
    fact = next(
        e for e in store.inspect_domain_events(ROOM) if e.type == "actor.sanity_loss"
    )
    await invoke_world_action(store, "rest")
    ledger = store.inspect_state(ROOM).actors[ACTOR].sanity
    late = fact.model_copy(
        update={
            "event_id": "late",
            "payload": {**fact.payload, "outcome_id": "late-original"},
        }
    )
    recovered = append_loss(ledger, late)
    assert recovered.window.loss_total == 0
    assert recovered.previous_windows[0].loss_total == 8
    assert append_loss(recovered, late) == recovered
    assert append_loss(recovered, fact) == recovered


async def test_actor_windows_are_isolated():
    from collaboration_framework.engine import InMemoryEngineStore
    from collaboration_framework.contracts.sanity import SanityPolicy
    from tests.sanity_fixtures import sandbox_content

    content = sandbox_content().model_copy(
        update={
            "sanity_policy": SanityPolicy(
                bout_mode="summary", window_boundary="world_day"
            )
        }
    )
    state = make_store(content).inspect_state(ROOM)
    state.actors["other"] = state.actors[ACTOR].model_copy(
        update={"actor_id": "other", "player_id": "other-player"}
    )
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    await cross_threshold(store)
    assert store.inspect_state(ROOM).actors["other"].sanity.window.loss_total == 0
    assert store.inspect_state(ROOM).actors["other"].conditions == ()
    await advance_until(store, 30)
    state = store.inspect_state(ROOM)
    assert state.actors[ACTOR].sanity.window.baseline_san == 48
    assert state.actors["other"].sanity.window.baseline_san == 60


async def test_temporary_insanity_upgrades_once_and_cancels_the_old_expiry():
    from tests.test_temporary_insanity import resolve_int
    from tests.sanity_fixtures import (
        sandbox_content,
        with_world_actions,
        invoke_world_action,
    )

    store = make_store(
        with_world_actions(
            sandbox_content(),
            {"end-bout": ("coc7.end_bout", {"reason": "keeper_intervention"})},
        )
    )
    pending = await settle(store, dice=(5,), request_id="initial-loss")
    await resolve_int(store, pending, dice=(8, 1, 1))
    old = next(
        c
        for c in store.inspect_state(ROOM).actors[ACTOR].condition_states
        if c.condition_id == "temporary_insanity"
    )
    await invoke_world_action(store, "end-bout", tag="first-bout-ended")
    await settle(store, dice=(4, 2, 1), request_id="underlying-stimulus")
    await invoke_world_action(store, "end-bout", tag="second-bout-ended")
    result = await settle(store, dice=(3, 3, 1), request_id="upgrade")
    state = store.inspect_state(ROOM)
    actor = state.actors[ACTOR]
    assert result.pending_decision is None
    assert set(actor.conditions) == {"indefinite_insanity", "madness_bout"}
    assert actor.sanity.window.loss_total == 12
    assert (
        next(
            c
            for c in actor.condition_states
            if c.application_key == old.application_key
        ).status
        == "removed"
    )
    assert not state.time_tasks
    assert (
        sum(
            e.type == "actor.indefinite_insanity"
            for e in store.inspect_domain_events(ROOM)
        )
        == 1
    )
