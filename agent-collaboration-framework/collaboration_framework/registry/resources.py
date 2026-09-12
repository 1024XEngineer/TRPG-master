"""Numeric policies have no game-system or module semantics."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from collaboration_framework.contracts import ContractError
from collaboration_framework.contracts.resources import (
    ChangeActorResourceEffect,
    FixedQuantity,
)

if TYPE_CHECKING:
    from .effects import ApplyContext, ApplyResult


@dataclass(frozen=True)
class ResourceRegistration:
    minimum: int | None


RESOURCES = {
    "hp": ResourceRegistration(minimum=None),
    "san": ResourceRegistration(minimum=0),
    "mp": ResourceRegistration(minimum=0),
    "luck": ResourceRegistration(minimum=0),
    "mythos": ResourceRegistration(minimum=0),
}


def apply_resource(
    effect: ChangeActorResourceEffect, ctx: "ApplyContext"
) -> "ApplyResult":
    from .effects import ApplyResult

    actor = ctx.state.actors.get(ctx.actor_id)
    before = getattr(actor.resources, effect.resource_id) if actor else None
    if before is None:
        raise ContractError(
            "ACTOR_RESOURCE_UNAVAILABLE: current actor resource is missing"
        )
    if isinstance(effect.quantity, FixedQuantity):
        amount, rolls = effect.quantity.value, ()
    elif ctx.simulation:
        # Validation simulates vocabulary/time writes only. It must never sample dice.
        amount, rolls = effect.quantity.count + effect.quantity.bonus, ()
    else:
        if ctx.services.roll_quantity is None:
            raise ContractError("RESOURCE_DICE_UNAVAILABLE")
        amount, rolls = ctx.services.roll_quantity(effect.quantity)
    requested_delta = amount if effect.direction == "increase" else -amount
    effective_delta = requested_delta
    if requested_delta < 0 and ctx.resource_decrease_limit is not None:
        effective_delta = -min(amount, ctx.resource_decrease_limit)
    if requested_delta > 0 and ctx.resource_increase_limit is not None:
        effective_delta = min(amount, ctx.resource_increase_limit)
    after = before + effective_delta
    minimum = RESOURCES[effect.resource_id].minimum
    if minimum is not None:
        after = max(minimum, after)
    resources = actor.resources.model_copy(update={effect.resource_id: after})
    actors = dict(ctx.state.actors)
    actors[ctx.actor_id] = actor.model_copy(update={"resources": resources})
    return ApplyResult(
        state=ctx.state.model_copy(update={"actors": actors}),
        event_type="actor.resource_changed",
        payload={
            "actor_id": ctx.actor_id,
            "resource_id": effect.resource_id,
            "quantity": effect.quantity.to_json_dict(),
            "rolls": list(rolls),
            "requested_delta": requested_delta,
            "actual_delta": after - before,
            "before": before,
            "after": after,
            "reason_code": effect.reason_code,
            "action_request_id": ctx.action_request_id or ctx.request_id,
        },
    )


def validate_resource(effect, vocab, runtime, services):
    if effect.resource_id not in RESOURCES or not vocab.actor_ids:
        raise ContractError("ACTOR_RESOURCE_UNAVAILABLE")
