"""Pure Actor condition lifecycle operations (#485).

Conditions are authoritative state, while ``ActorState.conditions`` remains a
small player-safe projection for compatibility with existing rooms and views.
"""

from __future__ import annotations

from dataclasses import dataclass

from .models import ActorCondition, ConditionExpiry, GameState


@dataclass(frozen=True)
class ConditionMutation:
    state: GameState
    condition: ActorCondition | None
    changed: bool


def active_conditions(state: GameState, actor_id: str) -> tuple[ActorCondition, ...]:
    actor = state.actors.get(actor_id)
    if actor is None:
        return ()
    return tuple(item for item in actor.condition_states if item.status == "active")


def has_active_condition(state: GameState, actor_id: str, condition_id: str) -> bool:
    return any(item.condition_id == condition_id for item in active_conditions(state, actor_id))


def apply_condition(
    state: GameState,
    *,
    actor_id: str,
    condition_id: str,
    source: str,
    application_reason: str,
    application_key: str,
    expiry: ConditionExpiry | None = None,
    applied_event_id: str | None = None,
) -> ConditionMutation:
    """Apply once by stable key (and avoid duplicate active condition ids)."""

    actor = state.actors.get(actor_id)
    if actor is None:
        raise ValueError(f"unknown actor: {actor_id}")
    for existing in actor.condition_states:
        if existing.application_key == application_key:
            return ConditionMutation(state=state, condition=existing, changed=False)
    for existing in actor.condition_states:
        if existing.condition_id == condition_id and existing.status == "active":
            return ConditionMutation(state=state, condition=existing, changed=False)
    record = ActorCondition(
        condition_id=condition_id,
        source=source,
        application_reason=application_reason,
        application_key=application_key,
        expiry=expiry,
        applied_event_id=applied_event_id,
    )
    records = (*actor.condition_states, record)
    actors = dict(state.actors)
    actors[actor_id] = actor.model_copy(
        update={
            "condition_states": records,
            "conditions": tuple(
                dict.fromkeys(
                    item.condition_id for item in records if item.status == "active"
                )
            ),
        }
    )
    return ConditionMutation(
        state=state.model_copy(update={"actors": actors}, deep=True),
        condition=record,
        changed=True,
    )


def _finish_condition(
    state: GameState,
    *,
    actor_id: str,
    condition_id: str,
    status: str,
    reason: str,
    event_id: str | None,
) -> ConditionMutation:
    actor = state.actors.get(actor_id)
    if actor is None:
        raise ValueError(f"unknown actor: {actor_id}")
    index = next(
        (
            index
            for index, item in enumerate(actor.condition_states)
            if item.condition_id == condition_id and item.status == "active"
        ),
        None,
    )
    if index is None:
        return ConditionMutation(state=state, condition=None, changed=False)
    existing = actor.condition_states[index]
    record = existing.model_copy(
        update={
            "status": status,
            "removal_reason": reason,
            "removal_event_id": event_id,
        }
    )
    records = list(actor.condition_states)
    records[index] = record
    actors = dict(state.actors)
    actors[actor_id] = actor.model_copy(
        update={
            "condition_states": tuple(records),
            "conditions": tuple(
                dict.fromkeys(
                    item.condition_id for item in records if item.status == "active"
                )
            ),
        }
    )
    return ConditionMutation(
        state=state.model_copy(update={"actors": actors}, deep=True),
        condition=record,
        changed=True,
    )


def remove_condition(
    state: GameState,
    *,
    actor_id: str,
    condition_id: str,
    reason: str,
    event_id: str | None = None,
) -> ConditionMutation:
    return _finish_condition(
        state,
        actor_id=actor_id,
        condition_id=condition_id,
        status="removed",
        reason=reason,
        event_id=event_id,
    )


def consume_condition(
    state: GameState,
    *,
    actor_id: str,
    condition_id: str,
    reason: str,
    event_id: str | None = None,
) -> ConditionMutation:
    return _finish_condition(
        state,
        actor_id=actor_id,
        condition_id=condition_id,
        status="consumed",
        reason=reason,
        event_id=event_id,
    )


__all__ = [
    "ConditionMutation",
    "active_conditions",
    "apply_condition",
    "consume_condition",
    "has_active_condition",
    "remove_condition",
]
