"""Predicate registry (#347 Phase 1): the closed set of trigger-condition
names a v3 Rule's ``PredicateCondition`` may reference.

#226 §1 forbids scripts and arbitrary state paths in rules, so a rule can
only ask questions the Engine registered — this table *is* that closed set.
Each entry pairs a predicate name with the pure function that evaluates it
against the current ``GameState``. It is the single source of truth for two
call sites that, before this registry existed, each hand-rolled their own
opinion of the same four names:

- ``engine/rules_v3.py::evaluate_condition`` (execution-time — "does this
  rule fire right now"). A name with no entry evaluates to ``False``, the
  same fallback the historical ``_UNKNOWN_PREDICATE_IS_FALSE`` constant gave.
- ``module/validation_v3.py::_condition_issues`` (publish-time — "does this
  rule even reference something the Engine understands"). A name with no
  entry is now a hard publish-time rejection (``MODULE_V3_PREDICATE_UNKNOWN``)
  instead of a silent runtime no-op — the one deliberate, called-out behaviour
  change in issue #347's otherwise pure-refactor scope.

Only the predicate *name* is a closed set. Each evaluator still does its own
light ``args`` shape-checking and returns ``False`` on a bad shape rather
than raising — that runtime leniency is unchanged by this registry; adding
publish-time arg-schema validation is explicitly out of scope for this phase
(see issue #347 Phase 1 notes).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from pydantic import JsonValue

from collaboration_framework.contracts import matches_time_query

if TYPE_CHECKING:  # annotations only — see this package's __init__ docstring.
    # `module/validation_v3.py` imports this table to check predicate *names*
    # at publish time. Importing GameState for real would make that a
    # `module -> engine` edge, which docs/architecture.md §6 forbids.
    from collaboration_framework.engine.models import GameState

PredicateEvaluator = Callable[[dict[str, JsonValue], "GameState", str], bool]


def entity_state(state: GameState, entity_id: str) -> dict:
    """The one authoritative read of an entity's state flags.

    An entity carrying an `item_component` gets materialised into
    `item_instances`, and `ChangeEntityStateEffect` then writes **only** to that
    record (it is the versioned one). Reading just `runtime_entities`/`entities`
    therefore never observes those writes: the authored defaults sit on one side
    while every subsequent update lands on the other, so any condition gated on
    such a flag — `visibility_conditions`, gated edges, event triggers — stays
    frozen at its initial value forever.

    Resolving here in the same precedence the write side uses (item wins) keeps
    a single source of truth per flag. The authored state stays the base so
    defaults survive: a fresh item instance starts with empty `values`.
    """

    runtime = state.runtime_entities.get(entity_id)
    base = runtime if runtime is not None else state.entities.get(entity_id, {})
    item = state.item_instances.get(entity_id)
    if item is None:
        return base
    return {**base, **item.state.values}


def _entity_state_is(args: dict[str, JsonValue], state: GameState, actor_id: str) -> bool:
    entity_id = args.get("entity_id")
    key = args.get("key")
    if not isinstance(entity_id, str) or not isinstance(key, str):
        return False
    expected = args.get("value", True)
    current = entity_state(state, entity_id).get(key)
    # An absent flag reads as False, which is how the authored `== false`
    # conditions are meant to fire on a fresh room.
    return (current if current is not None else False) == expected


def _time_of_day_is(args: dict[str, JsonValue], state: GameState, actor_id: str) -> bool:
    """通用规则层唯一能跨模组提问的时间语义（#415 §阶段一）。

    查询传四段值时精确匹配，传 `day` / `night` 时按别名集合匹配，所以既有的
    `time_of_day_is night` 不需要迁移，而新规则又能把同为夜晚的凌晨与晚上
    区分开——追书人的 `surveillance_available` 布尔闩就是因为区分不开才存在的。
    """

    return matches_time_query(state.world_time.time_segment, args.get("value"))


def _time_point_is(args: dict[str, JsonValue], state: GameState, actor_id: str) -> bool:
    """当前停在哪个模组声明的时间点上（#245 §8 的 CurrentTimePointPredicate）。

    这是模组私有的精确身份，`time_of_day_is` 答不了：追书人同时声明了
    `hour_18` 与 `hour_20`，两者都是 evening，粗粒度谓词在两个点各触发一次，
    所以模组只能拿一个布尔闩去手工去重。有了这个谓词，规则可以直接说清楚
    自己挂在哪一个点上。
    """

    return state.world_time.current_point_id == args.get("value")


def _world_time_at_least(args: dict[str, JsonValue], state: GameState, actor_id: str) -> bool:
    """世界时间是否已经走到（或越过）某个绝对时刻。

    比较走 `WorldTimePoint.absolute_hour`——那个属性早就存在且是全序，在这之前
    零消费者。跨天不需要调用方自己算：D0 18:00 < D1 02:00 由属性本身保证。
    """

    day_index = args.get("day_index", 0)
    hour_of_day = args.get("hour_of_day", 0)
    if not isinstance(day_index, int) or not isinstance(hour_of_day, int):
        return False
    if isinstance(day_index, bool) or isinstance(hour_of_day, bool):
        return False
    return state.world_time.current.absolute_hour >= day_index * 24 + hour_of_day


def _days_elapsed_at_least(args: dict[str, JsonValue], state: GameState, actor_id: str) -> bool:
    """开局当天是第 0 天，所以「第三天」写作 `{value: 2}`。"""

    value = args.get("value")
    if not isinstance(value, int) or isinstance(value, bool):
        return False
    return state.world_time.current.day_index >= value


def _information_is(args: dict[str, JsonValue], state: GameState, actor_id: str) -> bool:
    information_id = args.get("id")
    if not isinstance(information_id, str):
        return False
    return information_id in set(state.discovered_facts) | set(
        state.actor_discovered_facts.get(actor_id, ())
    )


def _core_resolved(args: dict[str, JsonValue], state: GameState, actor_id: str) -> bool:
    return state.core_resolved is bool(args.get("value", True))


PREDICATES: dict[str, PredicateEvaluator] = {
    "entity_state_is": _entity_state_is,
    "time_of_day_is": _time_of_day_is,
    "time_point_is": _time_point_is,
    "world_time_at_least": _world_time_at_least,
    "days_elapsed_at_least": _days_elapsed_at_least,
    "information_is": _information_is,
    "core_resolved": _core_resolved,
}


def is_registered(name: str) -> bool:
    return name in PREDICATES


def evaluate(
    name: str,
    args: dict[str, JsonValue],
    *,
    state: GameState,
    actor_id: str,
) -> bool:
    """Look up and run a predicate by name; an unregistered name reads False."""

    evaluator = PREDICATES.get(name)
    if evaluator is None:
        return False
    return evaluator(args, state, actor_id)


__all__ = [
    "PREDICATES",
    "PredicateEvaluator",
    "entity_state",
    "evaluate",
    "is_registered",
]
