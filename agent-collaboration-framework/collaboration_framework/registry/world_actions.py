"""World ruleset action registry (#347 Phase 4).

`InvokeRulesetActionStep.action_id` is the one place a v3 Rule names a world
ruleset action — "make this actor do the CoC-7e thing called X". It is free
text today, nothing in the repository reads it, and no executor exists for it:
a rule that reaches such a step suspends onto the Agenda and is ultimately
refused as `RULE_BUDGET_EXCEEDED`.

**This table is empty, and that is the correct current state.** It is not a
half-finished implementation. There is no v3 world action the Engine can
actually perform, so registering any name here would claim a capability that
does not exist — exactly the "registered but unrunnable" illusion #347 warns
about. The v2-era `_SUPPORTED_FORCE_ACTIONS` names in `engine/capabilities.py`
are deliberately *not* migrated in: they belonged to a runtime that is gone.

What this module is for is the place to put the first real one, and the
explicit statement that today there are none.

## Deliberately not wired into publish-time validation

A module containing `invoke_ruleset_action` with any `action_id` publishes
today as long as its step graph is well-formed, and it must keep publishing
after this phase. #347 §4.7 is explicit: a field with no consumer is not a
publish failure. Consulting this table to reject such a module would turn an
empty registry into a content-wide outage. "No executor" stays a runtime
outcome, on the same path it already took.

Shape follows `engine/capabilities.py`'s `SUPPORTED_WORLD_REFS`: a frozenset
of what the runtime can actually do, and a membership test.
"""

from __future__ import annotations

# Empty on purpose — see the module docstring. Adding a name here is a claim
# that the Engine can execute it, so it belongs in the same change that adds
# the executor, never ahead of one.
SUPPORTED_WORLD_ACTIONS: frozenset[str] = frozenset()


def is_registered(action_id: str) -> bool:
    """Whether the Engine has an executor for this world ruleset action.

    Currently False for every input.
    """

    return action_id in SUPPORTED_WORLD_ACTIONS


__all__ = ["SUPPORTED_WORLD_ACTIONS", "is_registered"]
