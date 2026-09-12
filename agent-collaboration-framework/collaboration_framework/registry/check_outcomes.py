"""Typed world-owned check consequences, expressed as generic effects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from pydantic import JsonValue

if TYPE_CHECKING:
    from collaboration_framework.engine.models import (
        EngineRuntimeSnapshot,
        GameState,
        DomainEvent,
        RuleCheckOrigin,
    )
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
    runtime: EngineRuntimeSnapshot
    actor_id: str
    origin: RuleCheckOrigin


@dataclass(frozen=True)
class CheckOutcome:
    effect: ChangeActorResourceEffect
    event_type: str
    decrease_limit: int | None = None
    audit: dict[str, JsonValue] = field(default_factory=dict)
    record: Callable[[GameState, DomainEvent], GameState] | None = None


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
    unknown = set(params) - {
        "success_loss",
        "failure_loss",
        "habit_cap",
        "sanity_source",
    }
    if unknown or context.check.actor_binding != "actor":
        raise ContractError("SANITY_PARAMETERS_INVALID")
    # Validate both branches before consuming the selected one.
    success = sanity_quantity(params.get("success_loss"))
    failure = sanity_quantity(params.get("failure_loss"))
    quantity = failure if context.result.degree in {"failure", "fumble"} else success
    from .sanity_sources import resolve_source
    from .sanity_ledger import ledger_for, append_loss, replace_ledger

    source = resolve_source(
        context.runtime.module_content,
        context.check,
        context.origin.rule_id,
        context.origin.step_id,
    )
    ledger = ledger_for(context.runtime, context.actor_id)
    cap = source.habit_cap if source else None
    if cap is not None and ledger.coverage == "legacy_gap":
        raise ContractError(
            "SANITY_HISTORY_CONFIRMATION_REQUIRED: capped source history is unproven"
        )
    limit = (
        max(0, cap - ledger.habituation.get(source.id, 0)) if cap is not None else None
    )
    return CheckOutcome(
        decrease_limit=limit,
        audit={
            "sanity_source": source.id if source else None,
            "habit_cap": cap,
            "source_remaining": limit,
            "history_coverage": ledger.coverage,
            "absolute_hour": context.runtime.game_state.world_time.current.absolute_hour,
        },
        record=lambda state, fact: replace_ledger(
            state, context.actor_id, append_loss(ledger, fact)
        ),
        effect=ChangeActorResourceEffect(
            resource_id="san",
            direction="decrease",
            quantity=quantity,
            reason_code="coc7.sanity_loss",
        ),
        event_type="actor.sanity_loss",
    )
