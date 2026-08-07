"""Deterministic execution of v3 `event` Rules (#226 §4, partial).

Scope, stated plainly: this executes the **effect chain** of an event-triggered
rule, synchronously, inside the transaction that produced the source event. It is
strictly more than v2's `event_rules` could do (which had no step graph at all)
and strictly less than the RuleAgenda #226 §4 specifies.

What is deliberately not here, because it needs a persisted agenda:

* `CheckStep` / `AdjudicatedCheckStep` — a check suspends the rule until the
  player answers, so it cannot resolve inside this transaction;
* `AwaitPlayerInputStep` — same, by definition;
* `InvokeRulesetActionStep` — needs the Ruleset executor bridge;
* cross-transaction resume, agenda ordering and lease recovery.

Rather than silently doing nothing at those steps, the walk stops and records
why, so the caller can see a rule was partially applied instead of guessing.
`RuleLimitsSpec` bounds the walk either way.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from collaboration_framework.contracts import (
    AdjudicatedCheckStep,
    AgentMatchTriggerSpec,
    AllCondition,
    AnyCondition,
    ConditionExpr,
    EffectStep,
    CheckStep,
    ContractError,
    EventTriggerSpec,
    FinishStep,
    ModuleContentV3,
    NotCondition,
    PredicateCondition,
    RuleSpecV3,
)

from .models import GameState

# Predicates a rule may name. #226 §1 forbids scripts and arbitrary state paths,
# so a rule can only ask questions the Engine registered.
_UNKNOWN_PREDICATE_IS_FALSE = False


@dataclass
class RuleWalk:
    """What one rule's step chain produced."""

    effects: list[object] = field(default_factory=list)
    suspended_at: str | None = None
    suspended_kind: str | None = None


def matching_event_rules(
    module: ModuleContentV3,
    *,
    event_type: str,
    state: GameState,
    actor_id: str,
) -> tuple[RuleSpecV3, ...]:
    """Event rules whose trigger fires for this event, in deterministic order.

    Ordering is `priority DESC, id ASC` — the same stable rule v2 used, so a
    module author's priorities keep meaning what they meant.
    """

    matched = [
        rule
        for rule in module.rules
        if isinstance(rule.trigger, EventTriggerSpec)
        and rule.trigger.event_type == event_type
        and evaluate_condition(rule.trigger.when, state=state, actor_id=actor_id)
    ]
    matched.sort(key=lambda rule: (-rule.priority, rule.id))
    return tuple(matched)


def evaluate_condition(
    condition: ConditionExpr | None,
    *,
    state: GameState,
    actor_id: str,
) -> bool:
    if condition is None:
        return True
    if isinstance(condition, AllCondition):
        return all(
            evaluate_condition(item, state=state, actor_id=actor_id)
            for item in condition.items
        )
    if isinstance(condition, AnyCondition):
        return any(
            evaluate_condition(item, state=state, actor_id=actor_id)
            for item in condition.items
        )
    if isinstance(condition, NotCondition):
        return not evaluate_condition(condition.item, state=state, actor_id=actor_id)
    if isinstance(condition, PredicateCondition):
        return _evaluate_predicate(condition, state=state, actor_id=actor_id)
    return False


def _evaluate_predicate(
    condition: PredicateCondition,
    *,
    state: GameState,
    actor_id: str,
) -> bool:
    args = condition.args
    if condition.predicate == "entity_state_is":
        entity_id = args.get("entity_id")
        key = args.get("key")
        if not isinstance(entity_id, str) or not isinstance(key, str):
            return False
        expected = args.get("value", True)
        current = _entity_state(state, entity_id).get(key)
        # An absent flag reads as False, which is how the authored `== false`
        # conditions are meant to fire on a fresh room.
        return (current if current is not None else False) == expected
    if condition.predicate == "time_of_day_is":
        return state.world_time.time_of_day == args.get("value")
    if condition.predicate == "information_is":
        information_id = args.get("id")
        if not isinstance(information_id, str):
            return False
        return information_id in set(state.discovered_facts) | set(
            state.actor_discovered_facts.get(actor_id, ())
        )
    if condition.predicate == "core_resolved":
        return state.core_resolved is bool(args.get("value", True))
    return _UNKNOWN_PREDICATE_IS_FALSE


def _entity_state(state: GameState, entity_id: str) -> dict:
    runtime = state.runtime_entities.get(entity_id)
    if runtime is not None:
        return runtime
    return state.entities.get(entity_id, {})


def walk_rule(rule: RuleSpecV3, *, branch_id: str | None = None) -> RuleWalk:
    """Follow one rule's steps, collecting effects until it must suspend."""

    steps = {step.id: step for step in rule.execution.steps}
    branches = {branch.id: branch for branch in rule.execution.branches}
    entry_id = branch_id
    if entry_id is None and isinstance(rule.trigger, EventTriggerSpec):
        entry_id = rule.trigger.entry_branch_id
    branch = branches.get(entry_id or "")
    walk = RuleWalk()
    if branch is None:
        return walk

    cursor: str | None = branch.entry_step_id
    visited: set[str] = set()
    while cursor is not None and len(visited) < rule.limits.max_steps:
        if cursor in visited:
            # A loop in the authored graph: stop rather than spin.
            walk.suspended_at = cursor
            walk.suspended_kind = "loop"
            return walk
        visited.add(cursor)
        step = steps.get(cursor)
        if step is None or isinstance(step, FinishStep):
            return walk
        if isinstance(step, EffectStep):
            walk.effects.append(step.effect)
            cursor = step.next_step_id
            continue
        # Everything else needs the persisted agenda.
        walk.suspended_at = step.id
        walk.suspended_kind = step.kind
        return walk
    if cursor is not None:
        walk.suspended_at = cursor
        walk.suspended_kind = "step_budget"
    return walk


__all__ = [
    "RuleWalk",
    "effects_after_cancel",
    "effects_after_degree",
    "evaluate_condition",
    "matching_event_rules",
    "pending_check_for",
    "resolve_rule_option",
    "walk_rule",
]


# --------------------------------------------------------------------------- #
# rule-owned checks (#226 §5): the Agent picks the method, the rule owns the
# outcome. The suspension point is the only place a check can appear, so the
# continuation is just "which rule, and where to resume from".
# --------------------------------------------------------------------------- #


def resolve_rule_option(
    module: ModuleContentV3,
    *,
    rule_id: str,
    option_id: str,
) -> tuple[RuleSpecV3, str]:
    """Validate an opaque Agent choice and return the branch it selects.

    Both ids come from the published Match View, so an id the module never
    declared means the Agent invented it — refused rather than guessed at.
    """

    rule = next((item for item in module.rules if item.id == rule_id), None)
    if rule is None or not isinstance(rule.trigger, AgentMatchTriggerSpec):
        raise ContractError(f"RuleDecision 引用了不存在的 agent_match Rule: {rule_id}")
    if option_id not in {option.id for option in rule.trigger.options}:
        raise ContractError(f"RuleDecision 引用了该 Rule 未声明的候选: {option_id}")
    if option_id not in {branch.id for branch in rule.execution.branches}:
        raise ContractError(f"Rule {rule_id} 的候选 {option_id} 没有对应分支")
    return rule, option_id


def pending_check_for(rule: RuleSpecV3, branch_id: str):
    """The check a branch runs before it may commit anything, if it has one.

    Returns `(step, effects_before)` — effects the walk already collected are
    committed with the check request, because they happened regardless of how
    the roll goes.
    """

    walk = walk_rule(rule, branch_id=branch_id)
    if walk.suspended_kind not in {"check", "adjudicated_check"}:
        return None, walk.effects
    step = next(
        (item for item in rule.execution.steps if item.id == walk.suspended_at),
        None,
    )
    if not isinstance(step, CheckStep | AdjudicatedCheckStep):
        return None, walk.effects
    return step, walk.effects


def effects_after_degree(rule: RuleSpecV3, step_id: str, degree: str) -> list:
    """Continue the rule from where the roll routed it (#226 §4)."""

    step = next((item for item in rule.execution.steps if item.id == step_id), None)
    if not isinstance(step, CheckStep | AdjudicatedCheckStep):
        return []
    resume_id = step.result_routes.get(degree)
    if resume_id is None:
        return []
    return _walk_from(rule, resume_id).effects


def effects_after_cancel(rule: RuleSpecV3, step_id: str) -> list:
    step = next((item for item in rule.execution.steps if item.id == step_id), None)
    if not isinstance(step, AdjudicatedCheckStep):
        return []
    return _walk_from(rule, step.cancel_step_id).effects


def _walk_from(rule: RuleSpecV3, step_id: str) -> RuleWalk:
    steps = {step.id: step for step in rule.execution.steps}
    walk = RuleWalk()
    cursor: str | None = step_id
    visited: set[str] = set()
    while cursor is not None and len(visited) < rule.limits.max_steps:
        if cursor in visited:
            walk.suspended_at, walk.suspended_kind = cursor, "loop"
            return walk
        visited.add(cursor)
        step = steps.get(cursor)
        if step is None or isinstance(step, FinishStep):
            return walk
        if isinstance(step, EffectStep):
            walk.effects.append(step.effect)
            cursor = step.next_step_id
            continue
        walk.suspended_at, walk.suspended_kind = step.id, step.kind
        return walk
    return walk
