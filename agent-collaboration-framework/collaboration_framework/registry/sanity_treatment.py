"""CoC7 monthly care: elapsed calendar time grants a review, never a cure."""

from __future__ import annotations

from calendar import monthrange
from datetime import timedelta
from types import SimpleNamespace

from collaboration_framework.contracts import ContractError
from collaboration_framework.contracts.resources import (
    ChangeActorResourceEffect,
    DiceQuantity,
)
from collaboration_framework.contracts.sanity import SanityTreatment
from .sanity_ledger import replace_ledger, append_loss
from .sanity_periods import reset_window


def month_boundary(policy, started_hour, month):
    if policy is None or policy.calendar_anchor is None:
        raise ContractError(
            "SANITY_CALENDAR_REQUIRED: author an explicit day-zero calendar date"
        )
    try:
        start = policy.calendar_anchor + timedelta(days=started_hour // 24)
        serial = start.year * 12 + start.month - 1 + month
        year, month_zero = divmod(serial, 12)
        target = start.replace(
            year=year,
            month=month_zero + 1,
            day=min(start.day, monthrange(year, month_zero + 1)[1]),
        )
        return (target - policy.calendar_anchor).days * 24 + started_hour % 24
    except (OverflowError, ValueError) as exc:
        raise ContractError("SANITY_CALENDAR_OUT_OF_RANGE") from exc


def _validate(context, *, review=False):
    from .rulesets import RulesetActionError

    expected = (
        {"treatment_id", "review_month", "safe"}
        if review
        else {"treatment_id", "kind", "safe"}
    )
    key = context.parameters.get("treatment_id")
    if (
        context.actor_binding != "actor"
        or set(context.parameters) != expected
        or not isinstance(key, str)
        or not key.strip()
        or len(key) > 120
        or context.parameters["safe"] is not True
    ):
        raise RulesetActionError(
            "SANITY_TREATMENT_INVALID", "治疗需要稳定编号与规则确认的安全环境"
        )
    if review:
        month = context.parameters["review_month"]
        if type(month) is not int or month < 1:
            raise RulesetActionError("SANITY_TREATMENT_INVALID", "复查月份必须是正整数")
    elif context.parameters["kind"] not in {"private", "institution"}:
        raise RulesetActionError("SANITY_TREATMENT_INVALID", "治疗方式无效")
    actor = context.state.actors.get(context.actor_id)
    if actor is None or actor.sanity is None:
        raise RulesetActionError("SANITY_HISTORY_UNINITIALIZED", "治疗需要理智账本")
    return actor, actor.sanity


def _services(context):
    if context.services is None:
        raise ContractError("RULESET_EFFECT_SERVICES_UNAVAILABLE")
    return context.services


def start_treatment(context):
    from .rulesets import RulesetActionError, RulesetActionResult

    actor, ledger = _validate(context)
    key, kind = context.parameters["treatment_id"], context.parameters["kind"]
    courses = (
        *ledger.treatment_history,
        *((ledger.treatment,) if ledger.treatment else ()),
    )
    previous = next((c for c in courses if c.treatment_id == key), None)
    if previous is not None:
        if previous.kind != kind:
            raise RulesetActionError(
                "SANITY_TREATMENT_ID_CONFLICT", "同一疗程不能更改治疗方式"
            )
        return RulesetActionResult(state=context.state)
    if "indefinite_insanity" not in actor.conditions or not actor.resources.san:
        raise RulesetActionError(
            "SANITY_TREATMENT_INELIGIBLE", "需要非零理智与活动的不定性疯狂状态"
        )
    if ledger.treatment and ledger.treatment.status == "active":
        raise RulesetActionError("SANITY_TREATMENT_ALREADY_ACTIVE", "当前疗程尚未结束")
    now = context.state.world_time.current.absolute_hour
    try:
        due = month_boundary(
            context.module_content.sanity_policy if context.module_content else None,
            now,
            1,
        )
    except ContractError as exc:
        raise RulesetActionError(str(exc).split(":", 1)[0], str(exc)) from exc
    if context.simulation:
        return RulesetActionResult(state=context.state)
    services = _services(context)
    state = context.state
    # Entering explicitly safe care ends the current bout, but not insanity.
    state = services.remove(state, condition_id="madness_bout", reason="safe_treatment")
    course = SanityTreatment(
        treatment_id=key,
        kind=kind,
        started_absolute_hour=now,
        due_absolute_hour=due,
    )
    history = (
        (*ledger.treatment_history, ledger.treatment)
        if ledger.treatment
        else ledger.treatment_history
    )
    ledger = ledger.model_copy(
        update={"treatment": course, "treatment_history": history}
    )
    state = replace_ledger(state, context.actor_id, ledger)
    state = reset_window(
        state, context.actor_id, ledger, "care:" + key, state.event_sequence
    )
    services.emit(
        "actor.treatment_started",
        {"actor_id": context.actor_id, "kind": kind, "review_after_hours": due - now},
    )
    return RulesetActionResult(state=state)


def interrupt_treatment(services, state, actor_id, outcome_id):
    ledger = state.actors[actor_id].sanity
    if (
        ledger is None
        or ledger.treatment is None
        or ledger.treatment.status != "active"
    ):
        return state
    course = ledger.treatment
    ledger = ledger.model_copy(
        update={
            "treatment": course.model_copy(
                update={"status": "interrupted", "interruption_outcome_id": outcome_id}
            )
        }
    )
    services.emit(
        "actor.treatment_interrupted", {"actor_id": actor_id, "reason": "new_trauma"}
    )
    return replace_ledger(state, actor_id, ledger)


def treatment_due(context):
    state = context.state
    for actor_id, actor in tuple(state.actors.items()):
        course = actor.sanity.treatment if actor.sanity else None
        if (
            course
            and course.status == "active"
            and not course.review_due_notified
            and state.world_time.current.absolute_hour >= course.due_absolute_hour
        ):
            state = replace_ledger(
                state,
                actor_id,
                actor.sanity.model_copy(
                    update={
                        "treatment": course.model_copy(
                            update={"review_due_notified": True}
                        )
                    }
                ),
            )
            context.services.emit(
                "actor.treatment_review_due",
                {"actor_id": actor_id, "status": "review_required"},
            )
    return state


def recover_indefinite(services, state, actor_id, reason):
    ledger = state.actors[actor_id].sanity
    if ledger is None or not state.actors[actor_id].resources.san:
        raise ContractError("SANITY_RECOVERY_INELIGIBLE")
    for kind in ("madness_bout", "indefinite_insanity"):
        state = services.remove(state, condition_id=kind, reason=reason)
    if ledger.treatment:
        ledger = ledger.model_copy(
            update={
                "treatment": ledger.treatment.model_copy(update={"status": "recovered"})
            }
        )
    state = replace_ledger(state, actor_id, ledger)
    return reset_window(
        state, actor_id, ledger, "recovery:" + reason, state.event_sequence
    )


def review_treatment(context):
    from .rulesets import RulesetActionError, RulesetActionResult

    actor, ledger = _validate(context, review=True)
    course = ledger.treatment
    key, month = context.parameters["treatment_id"], context.parameters["review_month"]
    if course is None or course.treatment_id != key:
        raise RulesetActionError("SANITY_TREATMENT_UNKNOWN", "疗程不存在")
    review_id = f"{key}:{month}"
    if review_id in course.reviews:
        return RulesetActionResult(state=context.state)
    if (
        course.status != "active"
        or "indefinite_insanity" not in actor.conditions
        or not actor.resources.san
    ):
        raise RulesetActionError(
            "SANITY_TREATMENT_INELIGIBLE", "疗程已中断或角色不适用"
        )
    if (
        month != course.next_review_month
        or context.state.world_time.current.absolute_hour < course.due_absolute_hour
    ):
        raise RulesetActionError(
            "SANITY_TREATMENT_NOT_DUE", "尚未满足本次复查的世界时间条件"
        )
    if context.simulation:
        return RulesetActionResult(state=context.state)
    services = _services(context)
    state = context.state
    rolls = {}
    next_month, stage, recovered = month + 1, course.stage, False
    outcome = "sanity_recheck"
    if stage == "treatment":
        treatment_roll, _ = services.quantity(DiceQuantity(count=1, sides=100))
        rolls["treatment"] = treatment_roll
        if treatment_roll <= (95 if course.kind == "private" else 50):
            outcome = "progress"
            san, mythos = actor.resources.san, actor.resources.mythos
            if san is None or mythos is None:
                raise ContractError("ACTOR_RESOURCE_UNAVAILABLE")
            state, _ = services.resource(
                state,
                ChangeActorResourceEffect(
                    resource_id="san",
                    direction="increase",
                    quantity=DiceQuantity(count=1, sides=3),
                    reason_code="coc7.treatment_gain",
                ),
                increase_limit=max(0, 99 - mythos - san),
            )
            stage = "sanity_recheck"
        elif treatment_roll >= 96:
            outcome = "deterioration"
            state, changed = services.resource(
                state,
                ChangeActorResourceEffect(
                    resource_id="san",
                    direction="decrease",
                    quantity=DiceQuantity(count=1, sides=6),
                    reason_code="coc7.treatment_loss",
                ),
            )
            fact = services.emit(
                "actor.sanity_loss",
                {
                    **changed.payload,
                    "outcome_id": "treatment:" + review_id,
                    "resource_event_id": changed.event_id,
                    "sanity_source": None,
                    "module_id": context.module_content.module_id,
                    "module_version": context.module_content.version,
                    "sanity_window_id": ledger.window.id if ledger.window else None,
                    "absolute_hour": state.world_time.current.absolute_hour,
                },
                visibility="hidden",
            )
            ledger = append_loss(state.actors[context.actor_id].sanity, fact)
            state = replace_ledger(state, context.actor_id, ledger)
            if (
                state.actors[context.actor_id].resources.san
                and fact.payload["actual_delta"] < 0
            ):
                from .insanity import start_bout

                bout_context = SimpleNamespace(
                    actor_id=context.actor_id,
                    services=services,
                    runtime=SimpleNamespace(
                        game_state=state, module_content=context.module_content
                    ),
                )
                state = start_bout(bout_context, state, "treatment:" + review_id)
            next_month = month + 2
        else:
            outcome = "no_progress"
    if stage == "sanity_recheck":
        sanity_roll, _ = services.quantity(DiceQuantity(count=1, sides=100))
        rolls["sanity"] = sanity_roll
        recovered = sanity_roll <= state.actors[context.actor_id].resources.san
    ledger = state.actors[context.actor_id].sanity
    assert ledger is not None
    course = course.model_copy(
        update={"reviews": (*course.reviews, review_id), "stage": stage}
    )
    ledger = ledger.model_copy(update={"treatment": course})
    state = replace_ledger(state, context.actor_id, ledger)
    if recovered:
        state = recover_indefinite(
            services, state, context.actor_id, "treatment:" + review_id
        )
    elif not state.actors[context.actor_id].resources.san:
        state = interrupt_treatment(
            services, state, context.actor_id, "treatment:" + review_id
        )
    else:
        policy = context.module_content.sanity_policy
        due = month_boundary(policy, course.started_absolute_hour, next_month)
        # A late review never permits several monthly checks at the same instant.
        # Wait at least one (or two after deterioration) further calendar months.
        earliest = month_boundary(
            policy,
            state.world_time.current.absolute_hour,
            2 if outcome == "deterioration" else 1,
        )
        while due // 24 < earliest // 24:
            next_month += 1
            due = month_boundary(policy, course.started_absolute_hour, next_month)
        # A deadline processed later on the same day must not skip a whole
        # treatment month. Keep that month's date and wait the remaining hours.
        due = max(due, earliest)
        course = course.model_copy(
            update={
                "next_review_month": next_month,
                "due_absolute_hour": due,
                "review_due_notified": False,
            }
        )
        state = replace_ledger(
            state, context.actor_id, ledger.model_copy(update={"treatment": course})
        )
    services.emit(
        "actor.treatment_reviewed",
        {
            "actor_id": context.actor_id,
            "outcome": outcome,
            "recovered": recovered,
            "rolls": rolls,
        },
    )
    return RulesetActionResult(state=state)
