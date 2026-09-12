"""Pure CoC7 accounting; consume only canonical loss facts."""

from __future__ import annotations
from typing import TYPE_CHECKING
from collaboration_framework.contracts.sanity import SanityLedger, SanityLoss
from .sanity_sources import LEGACY_SOURCES

if TYPE_CHECKING:
    from collaboration_framework.engine.models import (
        DomainEvent,
        EngineRuntimeSnapshot,
        GameState,
    )


def append_loss(ledger: SanityLedger, event: DomainEvent) -> SanityLedger:
    if event.type != "actor.sanity_loss":
        return ledger
    p = event.payload
    key = str(p["outcome_id"])
    if any(loss.outcome_id == key for loss in ledger.losses):
        return ledger
    source_id = p.get("sanity_source")
    if source_id is None:
        origin = p.get("rule_origin")
        if isinstance(origin, dict):
            source = LEGACY_SOURCES.get(
                (
                    p.get("module_id"),
                    p.get("module_version"),
                    origin.get("rule_id"),
                    origin.get("step_id"),
                )
            )
            source_id = source.id if source else None
    loss = SanityLoss(
        outcome_id=key,
        event_id=event.event_id,
        sequence=event.sequence,
        source_id=source_id,
        requested=max(0, -int(p["requested_delta"])),
        actual=max(0, -int(p["actual_delta"])),
        before=p["before"],
        after=p["after"],
        absolute_hour=p.get("absolute_hour"),
        module_id=p["module_id"],
        module_version=p["module_version"],
    )
    totals = dict(ledger.habituation)
    if loss.source_id is not None:
        totals[loss.source_id] = totals.get(loss.source_id, 0) + loss.actual
    return ledger.model_copy(
        update={"losses": (*ledger.losses, loss), "habituation": totals}
    )


def ledger_for(runtime: EngineRuntimeSnapshot, actor_id: str) -> SanityLedger:
    actor = runtime.game_state.actors[actor_id]
    if actor.sanity is not None:
        return actor.sanity
    # Old snapshots are not guessed from their current SAN. Canonical PR1 facts
    # prove losses after PR1; earlier history remains an explicit coverage gap.
    ledger = SanityLedger(
        coverage="canonical_history",
        coverage_start_sequence=runtime.game_state.event_sequence,
    )
    for event in sorted(runtime.event_history, key=lambda e: e.sequence):
        if event.actor_id == actor_id:
            ledger = append_loss(ledger, event)
    if runtime.game_state.event_sequence and not ledger.losses:
        ledger = ledger.model_copy(
            update={
                "coverage": "legacy_gap",
                "history_gaps": ("pre_canonical_history",),
            }
        )
    return ledger


def replace_ledger(state: GameState, actor_id: str, ledger: SanityLedger) -> GameState:
    actors = dict(state.actors)
    actors[actor_id] = actors[actor_id].model_copy(update={"sanity": ledger})
    return state.model_copy(update={"actors": actors})


def development_phase(context):
    from .rulesets import RulesetActionError, RulesetActionResult

    if set(context.parameters) != {"phase_id"} or context.actor_binding != "actor":
        raise RulesetActionError(
            "DEVELOPMENT_PHASE_INVALID", "发展阶段需要稳定 phase_id 和 actor"
        )
    phase_id = context.parameters["phase_id"]
    if not isinstance(phase_id, str) or not phase_id.strip() or len(phase_id) > 120:
        raise RulesetActionError("DEVELOPMENT_PHASE_INVALID", "phase_id 无效")
    actor = context.state.actors.get(context.actor_id)
    if actor is None or actor.sanity is None:
        raise RulesetActionError("SANITY_HISTORY_UNINITIALIZED", "必须先迁移理智账本")
    ledger = actor.sanity
    if phase_id in ledger.development_phases:
        return RulesetActionResult(state=context.state)
    totals = {key: max(0, value - 1) for key, value in ledger.habituation.items()}
    ledger = ledger.model_copy(
        update={
            "habituation": totals,
            "development_phases": (*ledger.development_phases, phase_id),
        }
    )
    return RulesetActionResult(
        state=replace_ledger(context.state, context.actor_id, ledger),
        event_type="actor.habituation_decayed",
        payload={"actor_id": context.actor_id, "phase_id": phase_id},
    )


def acknowledge_history(context):
    """An authored Keeper decision supplies a declared historical baseline."""
    from .rulesets import RulesetActionError, RulesetActionResult

    if (
        set(context.parameters) != {"cutover_id", "reason", "habituation"}
        or context.actor_binding != "actor"
    ):
        raise RulesetActionError(
            "SANITY_HISTORY_CONFIRMATION_INVALID", "需要明确的历史基线及原因"
        )
    key, reason, totals = (
        context.parameters[k] for k in ("cutover_id", "reason", "habituation")
    )
    if (
        not isinstance(key, str)
        or not key.strip()
        or not isinstance(reason, str)
        or not reason.strip()
        or not isinstance(totals, dict)
        or any(
            not isinstance(k, str) or type(v) is not int or v < 0
            for k, v in totals.items()
        )
    ):
        raise RulesetActionError("SANITY_HISTORY_CONFIRMATION_INVALID", "历史基线无效")
    actor = context.state.actors.get(context.actor_id)
    if actor is None:
        raise RulesetActionError("RULESET_ACTION_TARGET_UNKNOWN", "角色不存在")
    ledger = actor.sanity or SanityLedger(
        coverage="legacy_gap", history_gaps=("pre_canonical_history",)
    )
    marker = "history:" + key
    if marker in ledger.development_phases:
        return RulesetActionResult(state=context.state)
    if ledger.coverage != "legacy_gap":
        raise RulesetActionError(
            "SANITY_HISTORY_ALREADY_INITIALIZED", "已有确证账本不能覆盖"
        )
    ledger = ledger.model_copy(
        update={
            "habituation": dict(totals),
            "coverage": "canonical_history",
            "coverage_start_sequence": context.state.event_sequence,
            "development_phases": (*ledger.development_phases, marker),
        }
    )
    return RulesetActionResult(
        state=replace_ledger(context.state, context.actor_id, ledger),
        event_type="actor.sanity_history_confirmed",
        payload={"actor_id": context.actor_id, "cutover_id": key, "reason": reason},
    )
