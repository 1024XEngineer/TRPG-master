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

## Registration still adds no execution — but it no longer hides its absence

#347 registered `invoke_ruleset_action`, `create_npc_action_opportunity`,
`create_time_task` and `cancel_time_task` as suspending onto the Agenda with
status `running`, because that is what the pre-registry code reported. No
worker has ever existed to resume them, so `running` meant "parked forever,
with no signal": the Agenda sat in `GameState`, nothing advanced it, and the
execution still reported success. `presentation` and `await_player_input`
were the same hang wearing a more specific name — `awaiting_presentation` and
`awaiting_player_input` have never had a consumer either.

#398 §阶段一 keeps the "no new execution" scope — none of these six gain an
executor here — and changes only how their absence is reported. They now map
to `failed` with a `failure_code`, so the Agenda fails loudly and auditably
instead of hanging silently. Publish-time validation still does not gain an
"is there an executor for this action_id" check — #347 §4.7 is explicit that a
declared-but-unconsumed field is not a publish failure.

The one place that must NOT change is `adjudication.py::_owned_effects`: on
the agent_match path a suspended walk is already refused *visibly* as
`RULE_BUDGET_EXCEEDED`, and #398 lists removing that hard reject as out of
scope until executors exist.

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
# `schedules_time_task_and_continues` 走的是和 `produces_effect_and_continues`
# 同一条路：步骤在 walk 里就地产出一件待提交的事，游标继续往下走。它单独成一
# 个值只是因为待提交的东西不是 `step.effect`，而是步骤自身——目标时间要等到
# 提交那一刻才解析得出来（相对目标依赖当时的世界时钟）。
#
# 两者共用 `RuleWalk.effects` 这一个有序列表，所以「效果 A → 排任务 → 效果 B」
# 的作者顺序天然保住了；拆成两个列表就得再发明一套合并顺序（#415 §阶段四）。
WalkBehavior = Literal[
    "terminal",
    "produces_effect_and_continues",
    "schedules_time_task_and_continues",
    "suspends",
]

# The Agenda boundary a suspension maps to. `check` is the one kind whose
# answer is not fixed: it depends on the step's own `initiation_kind`.
#
# `failed` is a boundary like any other here: reaching a kind the Engine cannot
# execute is a definite answer about where the Agenda stopped, not an unknown.
AgendaStatus = Literal[
    "awaiting_active_check",
    "awaiting_passive_check",
    "awaiting_presentation",
    "awaiting_player_input",
    "running",
    "failed",
]

# Why an Agenda that reached a step kind stopped. Only failing statuses carry
# one; the codes are stable strings because they are published in the
# `rule.agenda_failed` audit event and in `AdjudicationExecution`.
STEP_KIND_HAS_NO_EXECUTOR = "step_kind_has_no_executor"
UNREGISTERED_STEP_KIND = "unregistered_step_kind"
# A walk stopped on a kind that has no suspension semantics at all (`effect`,
# `finish`). `agenda_status_for` has always answered `failed` here — reaching
# it means the walk disagrees with the registry — but the paired code was None,
# and a `failed` Agenda with no code reports `resolved` again through
# `_settled_status`. That is the silent success #398 removes, so the two must
# never disagree.
STEP_KIND_CANNOT_SUSPEND = "step_kind_cannot_suspend"


@dataclass(frozen=True)
class RuleStepRegistration:
    """Everything the Engine knows about one step kind."""

    walk_behavior: WalkBehavior
    # None for kinds that never suspend (`effect`, `finish`); for `check` the
    # value here is the active-check default and `agenda_status_for` refines it.
    agenda_status: AgendaStatus | None = None
    # Set only where `agenda_status == "failed"`: the reason to publish. Kinds
    # that never suspend leave it None and get `STEP_KIND_CANNOT_SUSPEND` from
    # `agenda_failure_code_for` instead.
    failure_code: str | None = None


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
    # The four below suspend onto the Agenda and have no worker that resumes
    # them. Until #398 they reported `running`, which is
    # indistinguishable from "a worker is about to pick this up" — so the
    # Agenda hung with no signal. They fail instead: same absence of an
    # executor, now visible.
    #
    # `presentation` and `await_player_input` belong here for the same reason
    # and not a weaker one. #288 §6 closed `PresentationStep` as *not wired*,
    # and no one claims a rule-owned player-input boundary either: grep
    # `awaiting_presentation` and `awaiting_player_input` across
    # `trpg-backend/app` and `collaboration_framework/host` and there are zero
    # consumers. A status nobody advances is a hang, and #398 §目标 5 requires
    # a suspension point the Engine cannot move past to fail visibly. Neither
    # kind appears in any published module, so nothing authored today changes.
    "presentation": RuleStepRegistration(
        walk_behavior="suspends",
        agenda_status="failed",
        failure_code=STEP_KIND_HAS_NO_EXECUTOR,
    ),
    "await_player_input": RuleStepRegistration(
        walk_behavior="suspends",
        agenda_status="failed",
        failure_code=STEP_KIND_HAS_NO_EXECUTOR,
    ),
    "invoke_ruleset_action": RuleStepRegistration(
        walk_behavior="produces_effect_and_continues",
    ),
    "create_npc_action_opportunity": RuleStepRegistration(
        walk_behavior="suspends",
        agenda_status="failed",
        failure_code=STEP_KIND_HAS_NO_EXECUTOR,
    ),
    # 这两个在 #415 §阶段四 拿到了执行器，所以不再挂在上面那组里：它们就地
    # 排任务 / 取消任务，然后从 `next_step_id` 继续，不挂起 Agenda。
    "create_time_task": RuleStepRegistration(
        walk_behavior="schedules_time_task_and_continues",
    ),
    "cancel_time_task": RuleStepRegistration(
        walk_behavior="schedules_time_task_and_continues",
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
    """The Agenda boundary that suspending on this kind means.

    An unregistered kind fails rather than parking on `running`. Publish-time
    validation already rejects kinds outside the union, so reaching one at
    runtime means the graph outran the Engine — and there is by definition no
    executor for a kind nobody registered.
    """

    registration = STEP_KINDS.get(kind)
    if registration is None or registration.agenda_status is None:
        return "failed"
    # A passive rule check is the Engine asking on the rule's behalf; an active
    # one is the player's own action waiting on a roll.
    if (
        kind == "check"
        and isinstance(step, CheckStep)
        and step.check.initiation_kind == "passive_rule"
    ):
        return "awaiting_passive_check"
    return registration.agenda_status


def agenda_failure_code_for(kind: str) -> str | None:
    """Why suspending on this kind is a failure, or None if it is not one.

    The branches mirror `agenda_status_for` one for one, and they have to: a
    `failed` status with no code collapses back to `resolved` in
    `_settled_status`. `test_registry_rule_steps` locks the two together across
    every registered kind.
    """

    registration = STEP_KINDS.get(kind)
    if registration is None:
        return UNREGISTERED_STEP_KIND
    if registration.agenda_status is None:
        return STEP_KIND_CANNOT_SUSPEND
    return registration.failure_code


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
    "STEP_KIND_CANNOT_SUSPEND",
    "STEP_KIND_HAS_NO_EXECUTOR",
    "UNREGISTERED_STEP_KIND",
    "AgendaStatus",
    "RuleStepRegistration",
    "WalkBehavior",
    "agenda_failure_code_for",
    "agenda_status_for",
    "is_registered",
    "is_registered_actor_binding",
    "next_step_ids",
    "registration_for",
    "walk_behavior_of",
]
