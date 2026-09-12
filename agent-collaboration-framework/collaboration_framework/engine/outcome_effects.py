"""Generic transactional effects used by world-owned check consequences."""

from __future__ import annotations
from hashlib import sha256
from uuid import uuid4

from collaboration_framework.contracts import (
    CreateTimeTaskStep,
    TimeTaskSpec,
    TimeTaskTargetSpec,
)
from collaboration_framework.contracts.resources import DiceQuantity
from .models import ConditionExpiry, DomainEvent
from .conditions import apply_condition, remove_condition
from .time_tasks import create_time_task


class OutcomeEffectSession:
    def __init__(self, runtime, *, request_id, actor_id, dice, offset):
        self.runtime, self.request_id, self.actor_id, self.dice = (
            runtime,
            request_id,
            actor_id,
            dice,
        )
        self.offset = offset
        self.events = []
        self.resource_runner = None

    def quantity(self, quantity: DiceQuantity):
        return self.dice.quantity(quantity)

    def emit(self, event_type, payload, *, visibility="public"):
        event = DomainEvent(
            event_id="evt_" + uuid4().hex,
            sequence=self.runtime.game_state.event_sequence
            + self.offset
            + len(self.events)
            + 1,
            type=event_type,
            room_id=self.runtime.game_state.room_id,
            actor_id=payload.get("actor_id", self.actor_id),
            client_action_id=self.request_id,
            cause=self.request_id,
            visibility=visibility,
            payload=payload,
        )
        self.events.append(event)
        return event

    def resource(self, state, effect, *, increase_limit=None):
        if self.resource_runner is None:
            from collaboration_framework.contracts import ContractError

            raise ContractError("RULESET_RESOURCE_SERVICES_UNAVAILABLE")
        state, events = self.resource_runner(state, effect, increase_limit)
        self.events.extend(events)
        return state, events[0]

    def task(self, state, *, key, absolute_hour):
        step = CreateTimeTaskStep(
            id="ruleset_timer",
            next_step_id="finish",
            task=TimeTaskSpec(
                task_key="ruleset_" + sha256(key.encode()).hexdigest()[:32],
                target=TimeTaskTargetSpec(
                    day_index=absolute_hour // 24, hour_of_day=absolute_hour % 24
                ),
                visibility="hidden",
                on_due_branch_id="notify",
                bindings={"actor_id": self.actor_id},
            ),
        )
        state, task, _ = create_time_task(
            self.runtime.module_content, state, step, rule_id="engine_ruleset"
        )
        self.emit(
            "time.task_created",
            {
                "actor_id": self.actor_id,
                "task_id": task.task_id,
                "occurrence_id": task.occurrence_id,
            },
            visibility="hidden",
        )
        return state, task.task_id

    def cancel_task(self, state, *, task_id, reason):
        from collaboration_framework.contracts import CancelTimeTaskStep
        from .time_tasks import cancel_time_task

        task = state.time_tasks.get(task_id)
        if task is None or task.status != "scheduled":
            return state
        state, _ = cancel_time_task(
            state,
            CancelTimeTaskStep(
                id="ruleset_cancel",
                task_key=task.task_key,
                bindings=task.bindings,
                reason_code=reason,
                next_step_id="finish",
            ),
            rule_id=task.rule_id,
        )
        self.emit(
            "time.task_cancelled",
            {"actor_id": self.actor_id, "task_id": task_id, "reason": reason},
            visibility="hidden",
        )
        return state

    def condition(self, state, *, condition_id, key, source, hours, details):
        if any(
            c.application_key == key
            for c in state.actors[self.actor_id].condition_states
        ):
            return state
        if any(
            c.condition_id == condition_id and c.status == "active"
            for c in state.actors[self.actor_id].condition_states
        ):
            return state
        expiry = None
        if hours is not None:
            absolute = state.world_time.current.absolute_hour + hours
            step = CreateTimeTaskStep(
                id="condition_expiry",
                next_step_id="finish",
                task=TimeTaskSpec(
                    task_key="condition_" + sha256(key.encode()).hexdigest()[:32],
                    target=TimeTaskTargetSpec(
                        day_index=absolute // 24, hour_of_day=absolute % 24
                    ),
                    visibility="hidden",
                    on_due_branch_id="expire",
                    bindings={"actor_id": self.actor_id, "application_key": key},
                ),
            )
            state, task, _ = create_time_task(
                self.runtime.module_content, state, step, rule_id="engine_condition"
            )
            expiry = ConditionExpiry(
                kind="time_task", reference_id=task.task_id, absolute_hour=absolute
            )
            self.emit(
                "time.task_created",
                {
                    "actor_id": self.actor_id,
                    "task_id": task.task_id,
                    "occurrence_id": task.occurrence_id,
                },
                visibility="hidden",
            )
        mutation = apply_condition(
            state,
            actor_id=self.actor_id,
            condition_id=condition_id,
            source=source,
            application_reason="check_consequence",
            application_key=key,
            expiry=expiry,
        )
        if not mutation.changed:
            return state
        event = self.emit(
            "actor.condition_applied",
            {"actor_id": self.actor_id, "condition_id": condition_id, **details},
        )
        actor = mutation.state.actors[self.actor_id]
        records = tuple(
            c.model_copy(
                update={"details": details, "applied_event_id": event.event_id}
            )
            if c.application_key == key
            else c
            for c in actor.condition_states
        )
        actors = dict(mutation.state.actors)
        actors[self.actor_id] = actor.model_copy(update={"condition_states": records})
        return mutation.state.model_copy(update={"actors": actors})

    def remove(self, state, *, condition_id, reason):
        if not any(
            c.condition_id == condition_id and c.status == "active"
            for c in state.actors[self.actor_id].condition_states
        ):
            return state
        event = self.emit(
            "actor.condition_removed",
            {"actor_id": self.actor_id, "condition_id": condition_id, "reason": reason},
        )
        condition = next(
            c
            for c in state.actors[self.actor_id].condition_states
            if c.condition_id == condition_id and c.status == "active"
        )
        state = remove_condition(
            state,
            actor_id=self.actor_id,
            condition_id=condition_id,
            reason=reason,
            event_id=event.event_id,
        ).state
        if condition.expiry and condition.expiry.kind == "time_task":
            task = state.time_tasks.get(condition.expiry.reference_id)
            if task is not None and task.status == "scheduled":
                from collaboration_framework.contracts import CancelTimeTaskStep
                from .time_tasks import cancel_time_task

                state, _ = cancel_time_task(
                    state,
                    CancelTimeTaskStep(
                        id="condition_cancel",
                        task_key=task.task_key,
                        bindings=task.bindings,
                        reason_code=reason,
                        next_step_id="finish",
                    ),
                    rule_id=task.rule_id,
                )
                self.emit(
                    "time.task_cancelled",
                    {
                        "actor_id": self.actor_id,
                        "task_id": task.task_id,
                        "reason": reason,
                    },
                    visibility="hidden",
                )
        return state


def expire_conditions(runtime, state, events, *, request_id, dice, offset):
    emitted = []
    for event in events:
        if event.type not in {"time.point_entered", "time.task_due"}:
            continue
        for actor_id, actor in tuple(state.actors.items()):
            service = OutcomeEffectSession(
                runtime,
                request_id=request_id,
                actor_id=actor_id,
                dice=dice,
                offset=offset + len(emitted),
            )
            for condition in actor.condition_states:
                expiry = condition.expiry
                if condition.status != "active" or expiry is None:
                    continue
                due = (
                    event.type == "time.task_due"
                    and expiry.kind == "time_task"
                    and expiry.reference_id == event.payload.get("task_id")
                )
                if event.type == "time.point_entered" and expiry.kind == "time_point":
                    due = (
                        expiry.absolute_hour == state.world_time.current.absolute_hour
                        if expiry.absolute_hour is not None
                        else expiry.reference_id == event.payload.get("point_id")
                    )
                if due:
                    state = service.remove(
                        state, condition_id=condition.condition_id, reason="expiry"
                    )
            emitted.extend(service.events)
    return state, tuple(emitted)


def bind_authored_expiries(runtime, before, after, actor_id):
    """Bind new daily point references once; old snapshots keep their legacy meaning."""
    from collaboration_framework.contracts import ContractError
    from .time_tasks import resolve_target, _refuse_beyond_terminal

    old_keys = {c.application_key for c in before.actors[actor_id].condition_states}
    actor = after.actors[actor_id]
    records = []
    for condition in actor.condition_states:
        expiry = condition.expiry
        if condition.application_key not in old_keys and expiry is not None:
            if expiry.kind == "time_point":
                moment = resolve_target(
                    runtime.module_content,
                    after,
                    TimeTaskTargetSpec(point_id=expiry.reference_id),
                )
                _refuse_beyond_terminal(runtime.module_content, moment)
                condition = condition.model_copy(
                    update={
                        "expiry": expiry.model_copy(
                            update={"absolute_hour": moment.absolute_hour}
                        )
                    }
                )
            elif (
                expiry.reference_id not in after.time_tasks
                or after.time_tasks[expiry.reference_id].status != "scheduled"
            ):
                raise ContractError("CONDITION_EXPIRY_TASK_UNAVAILABLE")
        records.append(condition)
    actors = dict(after.actors)
    actors[actor_id] = actor.model_copy(update={"condition_states": tuple(records)})
    return after.model_copy(update={"actors": actors})
