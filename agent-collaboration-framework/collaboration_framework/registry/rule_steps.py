"""Rule step registry (#347 Phase 3): the closed set of step kinds a v3 Rule's
execution graph may contain, and what the Engine does when it reaches one.

Four places used to hardcode their own opinion of the ten step kinds, each
with its own `isinstance` chain: `contracts/module_v3.py::_step_targets` (where
can this step jump to), `engine/rules_v3.py::walk_rule_from` (does the walk
continue, finish, or suspend here), `engine/rules_v3.py::agenda_status_for_walk`
(which Agenda boundary does suspending here mean), and
`module/validation_v3.py::_rule_issues` (what must hold about this step at
publish time). A kind added to the union but missed in one of the four failed
silently.

## Scope: registration and static checking only

This phase deliberately implements **no new execution**. In particular
`invoke_ruleset_action` has no executor anywhere in the repository and must
still have none after this: a rule reaching that step suspends, exactly as
before, and is refused downstream as `RULE_BUDGET_EXCEEDED`. Publish-time
validation likewise does not gain an "is there an executor for this
action_id" check — #347 §4.7 is explicit that a declared-but-unconsumed field
is not a publish failure. Giving that kind real behaviour is a separate issue.

## Why `next_step_ids` delegates instead of owning

`_step_targets` cannot move here: `RuleExecutionSpec`'s own model validator
calls it to reject a step that jumps to a nonexistent id, and `contracts` is
forbidden from importing any component package (docs/architecture.md §6). It
stays the single implementation and this table surfaces it, so there is still
one source of truth for "where can this step go".
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from collaboration_framework.contracts.module_v3 import (
    CheckStep,
    RuleStepSpec,
    _step_targets,
)

# What reaching a step does to a walk in progress.
#
# `suspends` is the overwhelming default: eight of the ten kinds park the walk
# on the durable RuleAgenda and let something else pick it up. They are one
# behaviour, not eight, and are registered as such rather than as eight
# near-identical entries.
WalkBehavior = Literal["terminal", "produces_effect_and_continues", "suspends"]

# The Agenda boundary a suspension maps to. `check` is the one kind whose
# answer is not fixed: it depends on the step's own `initiation_kind`.
AgendaStatus = Literal[
    "awaiting_active_check",
    "awaiting_passive_check",
    "awaiting_presentation",
    "awaiting_player_input",
    "running",
]


@dataclass(frozen=True)
class RuleStepRegistration:
    """Everything the Engine knows about one step kind."""

    walk_behavior: WalkBehavior
    # None for kinds that never suspend (`effect`, `finish`); for `check` the
    # value here is the active-check default and `agenda_status_for` refines it.
    agenda_status: AgendaStatus | None = None


STEP_KINDS: dict[str, RuleStepRegistration] = {
    "effect": RuleStepRegistration(walk_behavior="produces_effect_and_continues"),
    "finish": RuleStepRegistration(walk_behavior="terminal"),
    "check": RuleStepRegistration(
        walk_behavior="suspends",
        agenda_status="awaiting_active_check",
    ),
    "adjudicated_check": RuleStepRegistration(
        walk_behavior="suspends",
        agenda_status="awaiting_active_check",
    ),
    "presentation": RuleStepRegistration(
        walk_behavior="suspends",
        agenda_status="awaiting_presentation",
    ),
    "await_player_input": RuleStepRegistration(
        walk_behavior="suspends",
        agenda_status="awaiting_player_input",
    ),
    # The four below suspend onto the Agenda and currently have no worker that
    # resumes them; `running` is what the pre-registry code reported for them
    # and must stay that way until an issue gives them behaviour.
    "invoke_ruleset_action": RuleStepRegistration(
        walk_behavior="suspends",
        agenda_status="running",
    ),
    "create_npc_action_opportunity": RuleStepRegistration(
        walk_behavior="suspends",
        agenda_status="running",
    ),
    "create_time_task": RuleStepRegistration(
        walk_behavior="suspends",
        agenda_status="running",
    ),
    "cancel_time_task": RuleStepRegistration(
        walk_behavior="suspends",
        agenda_status="running",
    ),
}

# `RuleCheckSpec.actor_binding` / `InvokeRulesetActionStep.actor_binding` are
# free-text today and every authored module only ever writes "actor".
# #347 §4.8 asks for the value space to be registered and loaded completely,
# and for nothing else: resolving a binding into an actual list of actors, and
# letting one suspension await N results, stay out of scope. These mirror
# `BindingSlotSpec.source`, which already enumerates the same concept for
# agent_match triggers.
ACTOR_BINDINGS: frozenset[str] = frozenset({"actor", "target", "scene", "location"})


def is_registered(kind: str) -> bool:
    return kind in STEP_KINDS


def registration_for(step: RuleStepSpec) -> RuleStepRegistration | None:
    return STEP_KINDS.get(step.kind)


def walk_behavior_of(step: RuleStepSpec) -> WalkBehavior:
    """Whether a walk ends, continues, or parks when it reaches this step.

    An unregistered kind suspends: refusing to guess is what the original
    `walk_rule_from` did with its catch-all, and a walk that parks is
    recoverable where a walk that guessed wrong is not.
    """

    registration = STEP_KINDS.get(step.kind)
    return registration.walk_behavior if registration is not None else "suspends"


def agenda_status_for(kind: str, step: RuleStepSpec | None) -> AgendaStatus:
    """The Agenda boundary that suspending on this kind means."""

    registration = STEP_KINDS.get(kind)
    if registration is None or registration.agenda_status is None:
        return "running"
    # A passive rule check is the Engine asking on the rule's behalf; an active
    # one is the player's own action waiting on a roll.
    if (
        kind == "check"
        and isinstance(step, CheckStep)
        and step.check.initiation_kind == "passive_rule"
    ):
        return "awaiting_passive_check"
    return registration.agenda_status


def next_step_ids(step: RuleStepSpec) -> tuple[str, ...]:
    """Every step id this step can hand control to.

    Delegates to `contracts.module_v3._step_targets` — see this module's
    docstring for why that implementation cannot move here.
    """

    return _step_targets(step)


def is_registered_actor_binding(value: str) -> bool:
    return value in ACTOR_BINDINGS


__all__ = [
    "ACTOR_BINDINGS",
    "STEP_KINDS",
    "AgendaStatus",
    "RuleStepRegistration",
    "WalkBehavior",
    "agenda_status_for",
    "is_registered",
    "is_registered_actor_binding",
    "next_step_ids",
    "registration_for",
    "walk_behavior_of",
]
