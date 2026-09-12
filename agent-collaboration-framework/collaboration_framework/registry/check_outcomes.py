"""Typed world-owned check consequences, expressed as generic effects."""

from dataclasses import dataclass
from typing import Callable
import re
from pydantic import ValidationError

from collaboration_framework.contracts import CheckRoll, ContractError, RuleCheckSpec
from collaboration_framework.contracts.resources import (
    ChangeActorResourceEffect,
    DiceQuantity,
    FixedQuantity,
    ResourceQuantity,
)


@dataclass(frozen=True)
class CheckOutcomeContext:
    check: RuleCheckSpec
    result: CheckRoll


@dataclass(frozen=True)
class CheckOutcome:
    effect: ChangeActorResourceEffect
    event_type: str


CheckOutcomeHandler = Callable[[CheckOutcomeContext], CheckOutcome]


def _sanity_quantity(value: object) -> ResourceQuantity:
    # Legacy authored parameters are strings. No arbitrary formula language.
    if isinstance(value, int) and not isinstance(value, bool):
        return FixedQuantity(value=value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]{1,6}", value):
        return FixedQuantity(value=int(value))
    if isinstance(value, str) and (
        match := re.fullmatch(r"([0-9]{1,3})[dD]([0-9]{1,4})([+-][0-9]{1,5})?", value)
    ):
        return DiceQuantity(
            count=int(match[1]), sides=int(match[2]), bonus=int(match[3] or 0)
        )
    raise ContractError(
        "SANITY_LOSS_INVALID: expected a bounded fixed or dice quantity"
    )


def sanity_quantity(value: object) -> ResourceQuantity:
    try:
        return _sanity_quantity(value)
    except ValidationError as exc:
        raise ContractError(
            "SANITY_LOSS_INVALID: quantity outside supported limits"
        ) from exc


def coc7_sanity_outcome(context: CheckOutcomeContext) -> CheckOutcome:
    params = context.check.parameters
    unknown = set(params) - {"success_loss", "failure_loss", "habit_cap"}
    if unknown or context.check.actor_binding != "actor":
        raise ContractError("SANITY_PARAMETERS_INVALID")
    # Validate both branches before consuming the selected one.
    success = sanity_quantity(params.get("success_loss"))
    failure = sanity_quantity(params.get("failure_loss"))
    quantity = failure if context.result.degree in {"failure", "fumble"} else success
    return CheckOutcome(
        effect=ChangeActorResourceEffect(
            resource_id="san",
            direction="decrease",
            quantity=quantity,
            reason_code="coc7.sanity_loss",
        ),
        event_type="actor.sanity_loss",
    )
