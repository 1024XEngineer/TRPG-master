"""CoC7 insanity semantics; no Engine or persistence imports at runtime."""

from collaboration_framework.contracts import ContractError, RuleCheckSpec
from collaboration_framework.contracts.resources import DiceQuantity
from collaboration_framework.contracts.sanity import MadnessBout
from .check_outcomes import CheckOutcome, CheckOutcomeContext, OutcomeProgress
from .sanity_ledger import replace_ledger

BOUT_TYPES = (
    "amnesia",
    "robbed",
    "battered",
    "violence",
    "ideology",
    "significant_person",
    "institutionalized",
    "flee",
    "phobia",
    "mania",
)


def after_sanity_loss(context: CheckOutcomeContext) -> OutcomeProgress:
    state = context.runtime.game_state
    assert context.fact is not None
    actual = -int(context.fact.payload["actual_delta"])
    actor = state.actors[context.actor_id]
    if actual <= 0 or "madness_bout" in actor.conditions:
        return OutcomeProgress(state)
    if (
        "temporary_insanity" in actor.conditions
        or "indefinite_insanity" in actor.conditions
    ):
        return OutcomeProgress(
            start_bout(context, state, str(context.fact.payload["outcome_id"]))
        )
    if actual < 5:
        return OutcomeProgress(state)
    return OutcomeProgress(
        state,
        RuleCheckSpec(
            profile_id="coc7.insanity_int",
            actor_binding="actor",
            initiation_kind="passive_rule",
            allow_luck=False,
            allow_push=False,
            parameters={"outcome_id": context.fact.payload["outcome_id"]},
        ),
    )


def insanity_int_outcome(context: CheckOutcomeContext) -> CheckOutcome:
    if set(context.check.parameters) != {"outcome_id"}:
        raise ContractError("INSANITY_INT_PARAMETERS_INVALID")
    return CheckOutcome(resolve=resolve_int)


def resolve_int(context: CheckOutcomeContext) -> OutcomeProgress:
    state = context.runtime.game_state
    key = context.check.parameters.get("outcome_id")
    ledger = state.actors[context.actor_id].sanity
    if (
        not isinstance(key, str)
        or ledger is None
        or not any(
            loss.outcome_id == key and loss.actual >= 5 for loss in ledger.losses
        )
    ):
        raise ContractError("INSANITY_LOSS_ORIGIN_MISSING")
    if set(state.actors[context.actor_id].conditions) & {"temporary_insanity", "indefinite_insanity"}:
        return OutcomeProgress(state)
    if not context.result.passed:
        context.services.emit(
            "actor.insanity_resisted",
            {"actor_id": context.actor_id, "source_outcome_id": key},
        )
        return OutcomeProgress(state)
    # Mode validation occurs before any new condition or duration is sampled.
    require_summary(context)
    duration, rolls = context.services.quantity(DiceQuantity(count=1, sides=10))
    state = context.services.condition(
        state,
        condition_id="temporary_insanity",
        key="temporary:" + key,
        source="coc7.insanity",
        hours=duration,
        details={"duration_hours": duration, "duration_rolls": list(rolls)},
    )
    state = start_bout(context, state, key, maximum_hours=duration)
    context.services.emit(
        "actor.temporary_insanity",
        {
            "actor_id": context.actor_id,
            "duration_hours": duration,
            "source_outcome_id": key,
        },
    )
    return OutcomeProgress(state)


def require_summary(context):
    content, state = context.runtime.module_content, context.runtime.game_state
    mode = content.sanity_policy.bout_mode if content.sanity_policy else "auto"
    if mode == "auto":
        others = [
            actor for key, actor in state.actors.items() if key != context.actor_id
        ]
        mode = (
            "summary"
            if not others or all("madness_bout" in actor.conditions for actor in others)
            else "rounds"
        )
    if mode != "summary":
        raise ContractError(
            "INSANITY_ROUNDS_UNSUPPORTED: E6b is required for real-time bouts"
        )


def start_bout(context, state, key, maximum_hours=None):
    require_summary(context)
    actor = state.actors[context.actor_id]
    if "madness_bout" in actor.conditions:
        return state
    ledger = actor.sanity
    assert ledger is not None
    if any(b.source_outcome_id == key for b in ledger.bouts):
        return state
    if maximum_hours is None:
        condition = next(
            (
                c
                for c in actor.condition_states
                if c.condition_id == "temporary_insanity" and c.status == "active"
            ),
            None,
        )
        if (
            condition
            and condition.expiry
            and condition.expiry.absolute_hour is not None
        ):
            maximum_hours = max(
                1,
                condition.expiry.absolute_hour - state.world_time.current.absolute_hour,
            )
    kind, _ = context.services.quantity(DiceQuantity(count=1, sides=10))
    duration, _ = context.services.quantity(DiceQuantity(count=1, sides=10))
    hours = min(duration, maximum_hours) if maximum_hours is not None else duration
    bout = MadnessBout(
        application_key="bout:" + key,
        source_outcome_id=key,
        type_id=BOUT_TYPES[kind - 1],
        type_roll=kind,
        duration_roll=duration,
        duration_hours=hours,
        started_absolute_hour=state.world_time.current.absolute_hour,
    )
    state = context.services.condition(
        state,
        condition_id="madness_bout",
        key=bout.application_key,
        source="coc7.insanity",
        hours=hours,
        details={
            "bout_type": bout.type_id,
            "duration_hours": hours,
            "table_id": bout.table_id,
        },
    )
    state = replace_ledger(
        state,
        context.actor_id,
        ledger.model_copy(update={"bouts": (*ledger.bouts, bout)}),
    )
    context.services.emit(
        "actor.madness_bout",
        {
            "actor_id": context.actor_id,
            "bout_type": bout.type_id,
            "duration_hours": hours,
        },
    )
    return state


def safe_rest(context):
    from .rulesets import RulesetActionError, RulesetActionResult

    if (
        set(context.parameters) != {"rest_id", "safe", "uninterrupted"}
        or context.actor_binding != "actor"
    ):
        raise RulesetActionError("SAFE_REST_INVALID", "安全休息必须明确标识和完成条件")
    rest_id = context.parameters["rest_id"]
    if (
        not isinstance(rest_id, str)
        or not rest_id.strip()
        or context.parameters["safe"] is not True
        or context.parameters["uninterrupted"] is not True
    ):
        raise RulesetActionError("SAFE_REST_INCOMPLETE", "需要安全且未中断的完整休息")
    state = context.state
    actor = state.actors.get(context.actor_id)
    if actor is None or actor.sanity is None:
        raise RulesetActionError("SANITY_HISTORY_UNINITIALIZED", "缺少理智账本")
    if context.simulation or rest_id in actor.sanity.safe_rests:
        return RulesetActionResult(state=state)
    if context.services is None:
        raise RulesetActionError(
            "RULESET_EFFECT_SERVICES_UNAVAILABLE", "缺少条件执行器"
        )
    for condition_id in ("madness_bout", "temporary_insanity"):
        state = context.services.remove(
            state, condition_id=condition_id, reason="safe_rest"
        )
    ledger = actor.sanity.model_copy(
        update={"safe_rests": (*actor.sanity.safe_rests, rest_id)}
    )
    state = replace_ledger(state, context.actor_id, ledger)
    return RulesetActionResult(
        state=state,
        event_type="actor.rested_safely",
        payload={"actor_id": context.actor_id, "rest_id": rest_id},
    )


def end_bout(context):
    from .rulesets import RulesetActionError, RulesetActionResult

    if (
        set(context.parameters) != {"reason"}
        or context.actor_binding != "actor"
        or not isinstance(context.parameters["reason"], str)
        or not context.parameters["reason"].strip()
    ):
        raise RulesetActionError("BOUT_END_INVALID", "中断发作需要规则确认的原因")
    if context.simulation:
        return RulesetActionResult(state=context.state)
    if context.services is None:
        raise RulesetActionError(
            "RULESET_EFFECT_SERVICES_UNAVAILABLE", "缺少条件执行器"
        )
    return RulesetActionResult(
        state=context.services.remove(
            context.state,
            condition_id="madness_bout",
            reason=context.parameters["reason"],
        )
    )
