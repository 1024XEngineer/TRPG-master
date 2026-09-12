"""Authored treatment actions consume real world-time occurrences and dice."""

from datetime import date
import pytest
from collaboration_framework.contracts.sanity import SanityPolicy
from tests.sanity_fixtures import (
    ACTOR,
    ROOM,
    make_store,
    sandbox_content,
    with_world_actions,
    invoke_world_action,
    settle,
)
from tests.test_indefinite_insanity import cross_threshold, advance_until


def treatment_content(kind="private", *, calendar=True, terminal=None):
    content = sandbox_content().model_copy(
        update={
            "sanity_policy": SanityPolicy(
                bout_mode="summary",
                calendar_anchor=date(1924, 1, 31) if calendar else None,
            )
        }
    )
    if terminal:
        content = content.model_copy(
            update={
                "time_policy": content.time_policy.model_copy(
                    update={"terminal_point": terminal}
                )
            }
        )
    commands = {
        "start": (
            "coc7.start_treatment",
            {"treatment_id": "care-1", "kind": kind, "safe": True},
        ),
        "restart": (
            "coc7.start_treatment",
            {"treatment_id": "care-2", "kind": kind, "safe": True},
        ),
        "sleep": (
            "coc7.safe_rest",
            {"rest_id": "sleep", "safe": True, "uninterrupted": True},
        ),
        "develop": (
            "coc7.investigator_development",
            {"phase_id": "chapter-1", "recover_indefinite": True},
        ),
    }
    for month in (1, 2, 3, 4):
        commands[f"review-{month}"] = (
            "coc7.review_treatment",
            {"treatment_id": "care-1", "review_month": month, "safe": True},
        )
    return with_world_actions(content, commands)


async def begin_care(kind="private"):
    store = make_store(treatment_content(kind))
    await cross_threshold(store)
    await invoke_world_action(store, "start")
    return store


async def due(store, tag="due"):
    course = store.inspect_state(ROOM).actors[ACTOR].sanity.treatment
    await advance_until(store, course.due_absolute_hour, tag)


def test_calendar_months_preserve_original_day_and_leap_year():
    from collaboration_framework.registry.sanity_treatment import month_boundary

    policy = SanityPolicy(calendar_anchor=date(1924, 1, 31))
    assert month_boundary(policy, 12, 1) == 29 * 24 + 12
    assert month_boundary(policy, 12, 2) == 60 * 24 + 12
    assert (
        month_boundary(SanityPolicy(calendar_anchor=date(1923, 1, 31)), 12, 1)
        == 28 * 24 + 12
    )


async def test_elapsed_month_only_enables_review_and_no_automatic_cure():
    store = await begin_care()
    result = await invoke_world_action(store, "review-1", tag="early")
    assert result.status == "rule_failed"
    assert (
        store.inspect_domain_events(ROOM)[-1].payload["failure_code"]
        == "SANITY_TREATMENT_NOT_DUE"
    )
    await due(store)
    state = store.inspect_state(ROOM)
    assert state.actors[ACTOR].conditions == ("indefinite_insanity",)
    assert (
        state.time_tasks[state.actors[ACTOR].sanity.treatment.task_id].status
        == "completed"
    )
    assert (
        sum(
            e.type == "actor.treatment_review_due"
            for e in store.inspect_domain_events(ROOM)
        )
        == 1
    )
    assert not any(
        e.type == "actor.treatment_reviewed" for e in store.inspect_domain_events(ROOM)
    )


@pytest.mark.parametrize(
    "kind,roll",
    [("private", 1), ("private", 95), ("institution", 1), ("institution", 50)],
)
async def test_successful_care_gains_san_then_requires_passing_recovery_check(
    kind, roll
):
    store = await begin_care(kind)
    await due(store)
    result = await invoke_world_action(store, "review-1", dice=(roll, 3, 50))
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert result.status == "resolved"
    assert actor.resources.san == 51
    assert actor.conditions == ()
    assert actor.sanity.treatment.status == "recovered"
    assert actor.sanity.window.baseline_san == 51
    await invoke_world_action(store, "review-1", tag="replay")
    assert store.inspect_state(ROOM).actors[ACTOR].resources.san == 51
    await invoke_world_action(store, "start", tag="same-course")
    assert (
        store.inspect_state(ROOM).actors[ACTOR].sanity.treatment.status == "recovered"
    )


async def test_failed_san_recovery_waits_next_month_then_rolls_only_san():
    store = await begin_care()
    await due(store)
    await invoke_world_action(store, "review-1", dice=(95, 2, 99))
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 50
    assert actor.conditions == ("indefinite_insanity",)
    assert actor.sanity.treatment.stage == "sanity_recheck"
    assert actor.sanity.treatment.due_absolute_hour == 60 * 24 + 12
    await due(store, "next-month")
    await invoke_world_action(store, "review-2", dice=(50,))
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.conditions == ()
    assert actor.resources.san == 50


@pytest.mark.parametrize("roll", [51, 95])
async def test_institution_no_progress_preserves_san_and_schedules_next_month(roll):
    store = await begin_care("institution")
    await due(store)
    await invoke_world_action(store, "review-1", dice=(roll,))
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 48
    assert actor.sanity.treatment.stage == "treatment"
    assert actor.sanity.treatment.next_review_month == 2
    assert actor.conditions == ("indefinite_insanity",)


@pytest.mark.parametrize(
    "kind,roll", [("private", 96), ("private", 100), ("institution", 96)]
)
async def test_bad_care_loses_san_starts_bout_and_skips_next_month(kind, roll):
    store = await begin_care(kind)
    await due(store)
    await invoke_world_action(store, "review-1", dice=(roll, 2, 1, 1))
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 46
    assert actor.sanity.window.loss_total == 2
    assert actor.sanity.losses[-1].actual == 2
    assert set(actor.conditions) == {"indefinite_insanity", "madness_bout"}
    assert actor.sanity.treatment.next_review_month == 3
    assert actor.sanity.treatment.status == "active"
    result = await invoke_world_action(store, "review-2", tag="skip-month")
    assert result.status == "rule_failed"
    assert (
        store.inspect_domain_events(ROOM)[-1].payload["failure_code"]
        == "SANITY_TREATMENT_NOT_DUE"
    )


async def test_new_trauma_interrupts_course_and_requires_new_safe_course():
    store = await begin_care()
    first = store.inspect_state(ROOM).actors[ACTOR].sanity.treatment
    await settle(store, dice=(1, 1, 1), request_id="trauma")
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.sanity.treatment.status == "interrupted"
    assert store.inspect_state(ROOM).time_tasks[first.task_id].status == "cancelled"
    await invoke_world_action(store, "restart")
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.sanity.treatment.treatment_id == "care-2"
    assert actor.sanity.treatment_history[0].status == "interrupted"
    assert actor.conditions == ("indefinite_insanity",)


async def test_safe_rest_preserves_indefinite_but_explicit_development_can_recover():
    store = await begin_care()
    await invoke_world_action(store, "sleep")
    assert store.inspect_state(ROOM).actors[ACTOR].conditions == (
        "indefinite_insanity",
    )
    await invoke_world_action(store, "develop")
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.conditions == ()
    assert actor.resources.san == 48
    assert actor.sanity.treatment.status == "recovered"


async def test_undeclared_calendar_and_unreachable_month_refuse_without_partial_course():
    from collaboration_framework.contracts import ContractError

    for calendar, terminal in (
        (False, None),
        (True, {"point_id": "hour_18", "day_index": 1}),
    ):
        payload = treatment_content(calendar=calendar).to_json_dict()
        if terminal:
            payload["time_policy"]["terminal_point"] = terminal
        content = treatment_content().__class__.model_validate(payload)
        store = make_store(content)
        await cross_threshold(store)
        before = store.inspect_state(ROOM)
        if calendar:
            with pytest.raises(ContractError, match="invalid_time_task_target"):
                await invoke_world_action(store, "start")
        else:
            result = await invoke_world_action(store, "start")
            assert result.status == "rule_failed"
            assert (
                store.inspect_domain_events(ROOM)[-1].payload["failure_code"]
                == "SANITY_CALENDAR_REQUIRED"
            )
        after = store.inspect_state(ROOM)
        assert after.actors == before.actors
        assert after.time_tasks == before.time_tasks


async def test_recovery_projection_exposes_only_relative_review_status():
    from collaboration_framework.engine.projection_v3 import project_v3
    from tests.sanity_fixtures import PLAYER

    store = await begin_care()

    async def detail():
        async with store.transaction(ROOM) as tx:
            runtime = await tx.load_runtime()
        view = project_v3(runtime, player_id=PLAYER, actor_id=ACTOR)
        return next(
            c
            for c in view.self_actor.condition_details
            if c.id == "indefinite_insanity"
        )

    initial = await detail()
    assert initial.remaining_hours is None
    assert initial.recovery_status == "in_treatment"
    assert initial.review_after_hours == 29 * 24
    assert not (
        {"task_id", "calendar_anchor", "sanity_source", "absolute_hour"}
        & initial.to_json_dict().keys()
    )
    await due(store)
    current = await detail()
    assert current.recovery_status == "review_due"
    assert current.review_after_hours == 0
    assert current.remaining_hours is None


async def test_treatment_gain_obeys_mythos_maximum_and_retains_original_dice_audit():
    from collaboration_framework.engine import InMemoryEngineStore

    content = treatment_content()
    state = make_store(content).inspect_state(ROOM)
    actor = state.actors[ACTOR]
    state.actors[ACTOR] = actor.model_copy(
        update={"resources": actor.resources.model_copy(update={"mythos": 50})}
    )
    store = InMemoryEngineStore()
    store.register_room(module_content=content, initial_state=state)
    await cross_threshold(store)
    await invoke_world_action(store, "start")
    await due(store)
    await invoke_world_action(store, "review-1", dice=(95, 3, 99))
    actor = store.inspect_state(ROOM).actors[ACTOR]
    assert actor.resources.san == 49
    assert actor.sanity.window.baseline_san == 48
    event = next(
        e
        for e in store.inspect_domain_events(ROOM)
        if e.type == "actor.resource_changed"
        and e.payload["reason_code"] == "coc7.treatment_gain"
    )
    assert event.payload["rolls"] == [3]
    assert event.payload["requested_delta"] == 3
    assert event.payload["actual_delta"] == 1


async def test_late_review_never_backfills_multiple_months_at_one_instant():
    store = await begin_care("institution")
    await advance_until(store, 65 * 24 + 12, "late")
    await invoke_world_action(store, "review-1", dice=(51,))
    course = store.inspect_state(ROOM).actors[ACTOR].sanity.treatment
    assert course.next_review_month == 4
    assert (
        course.due_absolute_hour
        > store.inspect_state(ROOM).world_time.current.absolute_hour
    )
    assert course.reviews == ("care-1:1",)
