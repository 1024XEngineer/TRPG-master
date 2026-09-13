"""Compatibility for the mechanical TimeTasks written by early PR #532 builds."""

from .models import ConditionExpiry


def migrate_mechanical_timers(state):
    if not state.time_tasks:
        return state
    actors, tasks = dict(state.actors), dict(state.time_tasks)
    retired_occurrences = set()

    def retire(task):
        retired_occurrences.add(task.occurrence_id)
        if task.status == "scheduled":
            tasks[task.task_id] = task.model_copy(
                update={
                    "status": "cancelled",
                    "cancel_reason_code": "mechanical_deadline_migrated",
                }
            )

    for actor_id, actor in state.actors.items():
        records = []
        for condition in actor.condition_states:
            expiry = condition.expiry
            task = tasks.get(expiry.reference_id) if expiry else None
            if (
                expiry is not None
                and expiry.kind == "time_task"
                and expiry.absolute_hour is not None
                and task is not None
                and task.rule_id == "engine_condition"
                and task.branch_id == "expire"
                and task.bindings
                == {"actor_id": actor_id, "application_key": condition.application_key}
            ):
                retire(task)
                condition = condition.model_copy(
                    update={
                        "expiry": ConditionExpiry(
                            kind="absolute_hour", absolute_hour=expiry.absolute_hour
                        )
                    }
                )
            records.append(condition)
        ledger = actor.sanity
        course = ledger.treatment if ledger else None
        task = tasks.get(course.task_id) if course else None
        if (
            task is not None
            and task.rule_id == "engine_ruleset"
            and task.branch_id == "notify"
            and task.bindings == {"actor_id": actor_id}
        ):
            retire(task)
            ledger = ledger.model_copy(
                update={
                    "treatment": course.model_copy(
                        update={
                            "task_id": None,
                            "review_due_notified": course.review_due_notified
                            or task.status == "completed",
                        }
                    )
                }
            )
        if tuple(records) != actor.condition_states or ledger != actor.sanity:
            actors[actor_id] = actor.model_copy(
                update={"condition_states": tuple(records), "sanity": ledger}
            )
    if not retired_occurrences:
        return state
    # A story task at the same hour still owns its stop, including hidden tasks.
    scheduled = {t.occurrence_id for t in tasks.values() if t.status == "scheduled"}
    occurrences = {
        key: value
        for key, value in state.time_occurrences.items()
        if key not in retired_occurrences
        or key in scheduled
        or value.origin != "time_task"
    }
    return state.model_copy(
        update={"actors": actors, "time_tasks": tasks, "time_occurrences": occurrences}
    )
