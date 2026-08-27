"""World ruleset action registry (#347 Phase 4).

`InvokeRulesetActionStep.action_id` is the one place a v3 Rule names a world
ruleset action — "make this actor do the CoC-7e thing called X". Unknown action
ids remain free-text at publish time, but fail explicitly when reached.

The first executable action is ``coc7.apply_condition``. Its world-scoped
handler lives in ``registry/rulesets.py``; this compatibility table exposes
the closed set of action ids for callers that still use the old membership
API.

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

SUPPORTED_WORLD_ACTIONS: frozenset[str] = frozenset({"coc7.apply_condition"})


def is_registered(action_id: str) -> bool:
    """Whether the Engine has an executor for this world ruleset action.

False for unknown action ids.
    """

    return action_id in SUPPORTED_WORLD_ACTIONS


__all__ = ["SUPPORTED_WORLD_ACTIONS", "is_registered"]
