"""Mechanics expire at the next entered point without splitting story time."""

import pytest

from tests.sanity_fixtures import ACTOR, ROOM, make_store, settle
from tests.test_temporary_insanity import advance_time, resolve_int


async def test_hour_conditions_do_not_register_intermediate_time_tasks():
    store = make_store()
    pending = await settle(store, dice=(5,))
    await resolve_int(store, pending)
    state = store.inspect_state(ROOM)
    assert not state.time_tasks
    assert not state.time_occurrences
    await advance_time(store, "evening")
    state = store.inspect_state(ROOM)
    assert state.world_time.current.absolute_hour == 18
    assert state.actors[ACTOR].conditions == ("temporary_insanity",)


async def test_one_jump_expires_every_elapsed_condition_once():
    store = make_store()
    pending = await settle(store, dice=(5,))
    await resolve_int(store, pending, dice=(3, 3, 2))
    await advance_time(store, "evening")
    state = store.inspect_state(ROOM)
    assert state.world_time.current.absolute_hour == 18
    assert not state.actors[ACTOR].conditions
    await advance_time(store, "next-day")
    removed = [
        e.payload["condition_id"]
        for e in store.inspect_domain_events(ROOM)
        if e.type == "actor.condition_removed"
    ]
    assert sorted(removed) == ["madness_bout", "temporary_insanity"]
    assert not any(e.type == "time.task_due" for e in store.inspect_domain_events(ROOM))


async def test_deadline_exactly_at_the_entered_point_expires_immediately():
    store = make_store()
    pending = await settle(store, dice=(5,))
    await resolve_int(store, pending, dice=(6, 3, 6))
    await advance_time(store, "evening")
    state = store.inspect_state(ROOM)
    assert state.world_time.current.absolute_hour == 18
    assert not state.actors[ACTOR].conditions
    assert not state.time_tasks


def schedule(state, content, hour, *, rule="story", key="visitor", bindings=None):
    from collaboration_framework.contracts import (
        CreateTimeTaskStep,
        TimeTaskSpec,
        TimeTaskTargetSpec,
    )
    from collaboration_framework.engine.time_tasks import create_time_task

    return create_time_task(
        content,
        state,
        CreateTimeTaskStep(
            id="schedule",
            next_step_id="finish",
            task=TimeTaskSpec(
                task_key=key,
                target=TimeTaskTargetSpec(day_index=hour // 24, hour_of_day=hour % 24),
                visibility="hidden",
                on_due_branch_id="expire" if rule == "engine_condition" else "notify",
                bindings=bindings or {},
            ),
        ),
        rule_id=rule,
    )[:2]


def legacy_payload(state, content):
    """Reconstruct the pre-update persisted shape, not an already-normalized model."""
    expiries = {}
    for condition in state.actors[ACTOR].condition_states:
        if condition.status != "active" or condition.expiry is None:
            continue
        hour = condition.expiry.absolute_hour
        state, task = schedule(
            state,
            content,
            hour,
            rule="engine_condition",
            key=condition.application_key.replace(":", "_"),
            bindings={"actor_id": ACTOR, "application_key": condition.application_key},
        )
        expiries[condition.application_key] = {
            "kind": "time_task",
            "reference_id": task.task_id,
            "absolute_hour": hour,
        }
    payload = state.model_dump(mode="json")
    for condition in payload["actors"][ACTOR]["condition_states"]:
        if condition["application_key"] in expiries:
            condition["expiry"] = expiries[condition["application_key"]]
    return payload


async def test_old_snapshot_mechanical_stops_are_retired_before_next_jump():
    from collaboration_framework.engine import GameState, InMemoryEngineStore
    from tests.sanity_fixtures import sandbox_content

    content = sandbox_content()
    store = make_store(content)
    pending = await settle(store, dice=(5,))
    await resolve_int(store, pending)
    old = legacy_payload(store.inspect_state(ROOM), content)
    state = GameState.model_validate(old)
    assert len(state.time_tasks) == 2
    assert all(t.status == "cancelled" for t in state.time_tasks.values())
    assert not state.time_occurrences
    assert all(
        c.expiry.kind == "absolute_hour" for c in state.actors[ACTOR].condition_states
    )
    assert GameState.model_validate_json(state.model_dump_json()) == state
    restored = InMemoryEngineStore()
    restored.register_room(module_content=content, initial_state=state)
    await advance_time(restored, "evening")
    after = restored.inspect_state(ROOM)
    assert after.world_time.current.absolute_hour == 18
    assert after.actors[ACTOR].conditions == ("temporary_insanity",)


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("story_hour", [14, 15])
async def test_story_stop_survives_mechanical_expiry_even_when_shared(
    legacy, story_hour
):
    from collaboration_framework.engine import GameState, InMemoryEngineStore
    from tests.sanity_fixtures import sandbox_content

    content = sandbox_content()
    store = make_store(content)
    pending = await settle(store, dice=(5,))
    await resolve_int(store, pending)
    state, story = schedule(store.inspect_state(ROOM), content, story_hour)
    payload = (
        legacy_payload(state, content) if legacy else state.model_dump(mode="json")
    )
    state = GameState.model_validate(payload)
    assert state.time_tasks[story.task_id].status == "scheduled"
    assert story.occurrence_id in state.time_occurrences
    restored = InMemoryEngineStore()
    restored.register_room(module_content=content, initial_state=state)
    await advance_time(restored, "story-stop")
    after = restored.inspect_state(ROOM)
    assert after.world_time.current.absolute_hour == story_hour
    assert after.actors[ACTOR].conditions == ("temporary_insanity",)
    assert after.time_tasks[story.task_id].status == "completed"
    events = [
        e for e in restored.inspect_domain_events(ROOM) if e.type == "time.task_due"
    ]
    assert [e.payload["task_id"] for e in events] == [story.task_id]
    await advance_time(restored, "evening")
    assert restored.inspect_state(ROOM).world_time.current.absolute_hour == 18


@pytest.mark.parametrize("task_status", ["scheduled", "completed"])
async def test_old_treatment_task_becomes_a_deadline_without_duplicate_review_notice(
    task_status,
):
    from collaboration_framework.engine import GameState, InMemoryEngineStore
    from tests.test_sanity_treatment import begin_care, treatment_content
    from tests.test_indefinite_insanity import advance_until

    content = treatment_content()
    store = await begin_care()
    state = store.inspect_state(ROOM)
    course = state.actors[ACTOR].sanity.treatment
    # Move the deadline off the default points to expose an old inserted stop.
    hour = course.due_absolute_hour + 3
    state, task = schedule(
        state, content, hour, rule="engine_ruleset", bindings={"actor_id": ACTOR}
    )
    payload = state.model_dump(mode="json")
    old_course = payload["actors"][ACTOR]["sanity"]["treatment"]
    old_course.update(task_id=task.task_id, due_absolute_hour=hour)
    old_course.pop("review_due_notified")
    payload["time_tasks"][task.task_id]["status"] = task_status
    if task_status == "completed":
        payload["world_time"].update(
            current_point_id=task.occurrence_id,
            current={"day_index": hour // 24, "hour_of_day": hour % 24},
            current_time_segment="afternoon",
        )
        payload["time_occurrences"] = {}
    state = GameState.model_validate(payload)
    assert not state.time_occurrences
    assert state.actors[ACTOR].sanity.treatment.task_id is None
    assert GameState.model_validate_json(state.model_dump_json()) == state
    restored = InMemoryEngineStore()
    restored.register_room(module_content=content, initial_state=state)
    await advance_until(restored, hour + 3)
    await advance_time(restored, "later")
    events = restored.inspect_domain_events(ROOM)
    assert sum(e.type == "actor.treatment_review_due" for e in events) == (
        1 if task_status == "scheduled" else 0
    )
    assert restored.inspect_state(ROOM).actors[ACTOR].conditions == (
        "indefinite_insanity",
    )
