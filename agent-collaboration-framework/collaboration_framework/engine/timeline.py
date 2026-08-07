"""Ordered discrete timeline: where the room may jump to next (#245 §一.1).

The whole point of the discrete model is that "what time is it next" is an
authoritative, deterministic lookup rather than arithmetic on a duration. Callers
never say *how far* to advance; they say `advance_to_next` and the timeline
answers with exactly one point.

Scope note: this module resolves **default** points only. Story temporary points
(§一.5) insert extra occurrences between two default points and are resolved by
the same `next_point_after` once RuntimeTimeTask lands — the signature is chosen
so that adding them does not change any caller.
"""

from __future__ import annotations

from collaboration_framework.contracts import ContractError, ModuleContentV3, TimePointSpec

from .models import WorldTimePoint, WorldTimeState


def ordered_points(module_content: ModuleContentV3) -> tuple[TimePointSpec, ...]:
    return tuple(sorted(module_content.time_policy.default_points, key=lambda item: item.order))


def next_point_after(
    module_content: ModuleContentV3,
    world_time: WorldTimeState,
) -> tuple[TimePointSpec, WorldTimePoint]:
    """The single point the room is allowed to enter next.

    Wrapping past the last point of the day rolls `day_index` forward: the cycle
    is `00 → 06 → 12 → 18 → next-day 00`, so the last point's successor is the
    first point of the following day.
    """

    points = ordered_points(module_content)
    if not points:
        raise ContractError("time_next_point_not_found: 模组没有声明任何时间点")

    index = next(
        (i for i, item in enumerate(points) if item.id == world_time.current_point_id),
        None,
    )
    if index is None:
        # The room is parked on a point this module version no longer declares.
        # Refusing beats silently relocating the party to a different hour.
        raise ContractError(
            "time_next_point_not_found: 当前时间点不在模组时间线上: "
            f"{world_time.current_point_id}"
        )

    following = index + 1
    if following < len(points):
        target = points[following]
        day_index = world_time.current.day_index
    else:
        target = points[0]
        day_index = world_time.current.day_index + 1
    return target, WorldTimePoint(day_index=day_index, hour_of_day=target.hour_of_day)


def advanced_to_next(
    module_content: ModuleContentV3,
    world_time: WorldTimeState,
) -> WorldTimeState:
    """Pure resolution of one jump; committing it is the caller's transaction."""

    target, moment = next_point_after(module_content, world_time)
    return WorldTimeState(current=moment, current_point_id=target.id)
