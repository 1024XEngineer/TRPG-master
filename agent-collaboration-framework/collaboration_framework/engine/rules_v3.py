"""Deterministic v3 Rule walking and durable RuleAgenda helpers (#226 §4).

Rule effects may execute in the source transaction, but every blocking cursor is
materialised as a ``RuleAgenda`` in ``GameState``. Stores lease that same object
for cross-transaction work; a process restart therefore resumes the published
step graph instead of replaying already committed effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

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

from collaboration_framework.registry import predicates as predicate_registry

from .models import AgendaItem, AgendaSource, DomainEvent, GameState, RuleAgenda

# `entity_state` used to live here; it now lives in `registry/predicates.py`
# (the shared read every predicate evaluator uses). Re-imported by name so
# `adjudication.py` and `navigation.py` can keep doing
# `from .rules_v3 import entity_state` unchanged.
from collaboration_framework.registry.predicates import entity_state  # noqa: F401


@dataclass
class RuleWalk:
    """What one rule's step chain produced."""

    effects: list[object] = field(default_factory=list)
    suspended_at: str | None = None
    suspended_kind: str | None = None
    step_count: int = 0
    completed: bool = False


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
    """Delegates to `registry/predicates.py` (#347 Phase 1).

    An unregistered predicate name still reads False here, exactly as the
    inline `_UNKNOWN_PREDICATE_IS_FALSE` fallback did before the registry
    existed — this function's job is now just the lookup, not the four
    branches themselves.
    """

    return predicate_registry.evaluate(
        condition.predicate,
        condition.args,
        state=state,
        actor_id=actor_id,
    )


def walk_rule(rule: RuleSpecV3, *, branch_id: str | None = None) -> RuleWalk:
    """Follow one rule's steps, collecting effects until it must suspend."""

    branches = {branch.id: branch for branch in rule.execution.branches}
    entry_id = branch_id
    if entry_id is None and isinstance(rule.trigger, EventTriggerSpec):
        entry_id = rule.trigger.entry_branch_id
    branch = branches.get(entry_id or "")
    walk = RuleWalk()
    if branch is None:
        return walk

    return walk_rule_from(rule, branch.entry_step_id)


def walk_rule_from(rule: RuleSpecV3, step_id: str) -> RuleWalk:
    """Resume an immutable Rule graph from its persisted cursor."""

    steps = {step.id: step for step in rule.execution.steps}
    walk = RuleWalk()
    cursor: str | None = step_id
    visited: set[str] = set()
    while cursor is not None and walk.step_count < rule.limits.max_steps:
        if cursor in visited:
            # A loop in the authored graph: stop rather than spin.
            walk.suspended_at = cursor
            walk.suspended_kind = "loop"
            return walk
        visited.add(cursor)
        step = steps.get(cursor)
        walk.step_count += 1
        if step is None:
            walk.suspended_at = cursor
            walk.suspended_kind = "unknown_step"
            return walk
        if isinstance(step, FinishStep):
            walk.completed = True
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


def agenda_item_key(item: AgendaItem) -> tuple[int, int, str]:
    """The exact queue order frozen by #226 §4."""

    return (item.event_sequence, -item.rule_priority, item.rule_id)


def ordered_agenda_items(items: tuple[AgendaItem, ...]) -> tuple[AgendaItem, ...]:
    """Return a stable queue independent of input or database row order."""

    return tuple(sorted(items, key=agenda_item_key))


def create_rule_agenda(
    *,
    agenda_id: str,
    room_id: str,
    module: ModuleContentV3,
    correlation_id: str,
    root_source: AgendaSource,
    revision: str,
) -> RuleAgenda:
    """Create the durable root before any blocking Rule step can be reached."""

    return RuleAgenda(
        agenda_id=agenda_id,
        room_id=room_id,
        module_id=module.module_id,
        module_version=module.version,
        correlation_id=correlation_id,
        root_source=root_source,
        revision=revision,
    )


def agenda_item_for_event(rule: RuleSpecV3, event: DomainEvent) -> AgendaItem:
    trigger = rule.trigger
    if not isinstance(trigger, EventTriggerSpec):
        raise ContractError("只有 event Rule 可以进入 Event Agenda")
    return AgendaItem(
        source_event_id=event.event_id,
        event_sequence=event.sequence,
        rule_id=rule.id,
        rule_priority=rule.priority,
        branch_id=trigger.entry_branch_id,
    )


def agenda_status_for_walk(rule: RuleSpecV3, walk: RuleWalk) -> str:
    """Map a blocking step to the authoritative Agenda boundary."""

    if walk.suspended_kind in {"loop", "step_budget", "unknown_step"}:
        return "failed"
    if walk.suspended_kind == "check":
        step = next(
            (item for item in rule.execution.steps if item.id == walk.suspended_at),
            None,
        )
        if isinstance(step, CheckStep) and step.check.initiation_kind == "passive_rule":
            return "awaiting_passive_check"
        return "awaiting_active_check"
    if walk.suspended_kind == "adjudicated_check":
        return "awaiting_active_check"
    if walk.suspended_kind == "presentation":
        return "awaiting_presentation"
    if walk.suspended_kind == "await_player_input":
        return "awaiting_player_input"
    if walk.suspended_at is not None:
        return "running"
    return "stable"


def agenda_claim_key(agenda: RuleAgenda) -> tuple[int, int, str, str]:
    """Stable order when multiple runnable Agenda roots need a worker."""

    pending = [item for item in agenda.queue if item.status in {"queued", "running"}]
    if not pending:
        return (2**63 - 1, 0, "", agenda.agenda_id)
    first = min(pending, key=agenda_item_key)
    return (*agenda_item_key(first), agenda.agenda_id)


def agenda_is_claimable(agenda: RuleAgenda, *, now: datetime) -> bool:
    return agenda.status == "running" and (
        agenda.lease_expires_at is None or agenda.lease_expires_at <= now
    )


def resume_agenda_rule(
    agenda: RuleAgenda,
    module: ModuleContentV3,
) -> tuple[RuleSpecV3, RuleWalk]:
    """Reload the pinned Rule and continue from the persisted step cursor."""

    if (agenda.module_id, agenda.module_version) != (module.module_id, module.version):
        raise ContractError("RuleAgenda 与加载的 ModuleVersion 不一致")
    if agenda.current_rule_id is None or agenda.current_step_id is None:
        raise ContractError("RuleAgenda 没有可恢复的 Rule cursor")
    rule = next(
        (item for item in module.rules if item.id == agenda.current_rule_id), None
    )
    if rule is None:
        raise ContractError("RuleAgenda 引用的 Rule 不存在于固定 ModuleVersion")
    return rule, walk_rule_from(rule, agenda.current_step_id)


__all__ = [
    "RuleWalk",
    "agenda_claim_key",
    "agenda_is_claimable",
    "agenda_item_for_event",
    "agenda_item_key",
    "agenda_status_for_walk",
    "create_rule_agenda",
    "agent_match_scope_admits",
    "effects_after_cancel",
    "effects_after_degree",
    "evaluate_condition",
    "matching_event_rules",
    "ordered_agenda_items",
    "pending_check_for",
    "resolve_rule_option",
    "resume_agenda_rule",
    "walk_rule",
    "walk_rule_from",
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


def agent_match_scope_admits(
    rule: RuleSpecV3,
    *,
    location_id: str,
    action_family: str | None = None,
    target_kind: str | None = None,
    target_id: str | None = None,
) -> bool:
    """Whether this rule may fire in this situation. Empty scope = unconstrained.

    Publishing a candidate menu and accepting a decision must ask the *same*
    question. When only the publish side filtered, the menu was scoped but the
    submit side accepted any rule the module declared anywhere — so a model that
    named a rule for another location had it honoured. Both sides call this.

    The arguments narrow as the caller knows more: publishing knows only where
    the actor stands, submitting also knows what was aimed at and how.
    """

    trigger = rule.trigger
    if not isinstance(trigger, AgentMatchTriggerSpec):
        return False
    scope = trigger.scope
    if scope.location_ids and location_id not in scope.location_ids:
        return False
    if action_family is not None and scope.action_families:
        if action_family not in scope.action_families:
            return False
    if target_kind is not None and scope.target_kinds:
        if target_kind not in scope.target_kinds:
            return False
    if target_id is not None and scope.target_ids:
        if target_id not in scope.target_ids:
            return False
    return True


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
    return walk_rule_from(rule, resume_id).effects


def effects_after_cancel(rule: RuleSpecV3, step_id: str) -> list:
    step = next((item for item in rule.execution.steps if item.id == step_id), None)
    if not isinstance(step, AdjudicatedCheckStep):
        return []
    return walk_rule_from(rule, step.cancel_step_id).effects
