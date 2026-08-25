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

from collections.abc import Sequence

from collaboration_framework.contracts import (
    ContractError,
    ModuleContentV3,
    TimeAdvanceBlockReason,
    TimePointSpec,
    default_label_for,
)

from .models import WorldTimePoint, WorldTimeState


def ordered_points(module_content: ModuleContentV3) -> tuple[TimePointSpec, ...]:
    return tuple(sorted(module_content.time_policy.default_points, key=lambda item: item.order))


def _walk_position(
    points: Sequence[TimePointSpec],
    point_id: str,
    day_index: int,
) -> tuple[int, int]:
    """把一次 occurrence 压成可比较的 walk 坐标（#415 §阶段二）。

    环从起点开始走：同一天里 `order` 递增，越过末点回卷才 `day_index + 1`。
    所以 `(day_index, order)` 的字典序**就是**推进顺序，比较两次 occurrence
    的先后不需要再关心小时。
    """

    order = next(index for index, item in enumerate(points) if item.id == point_id)
    return day_index, order


def terminal_reached(
    module_content: ModuleContentV3,
    world_time: WorldTimeState,
) -> bool:
    """房间是否已经走到（或越过）模组声明的最后一刻。

    越过也算：异常状态下 fail closed 比继续推进安全——已经越过终点还能往前走，
    等于让时间线在作者根本没写过的地方继续跑。

    没声明终点的模组永远返回 False，维持现有环形回卷。
    """

    terminal = module_content.time_policy.terminal_point
    if terminal is None:
        return False

    points = ordered_points(module_content)
    try:
        current = _walk_position(points, world_time.current_point_id, world_time.current.day_index)
        end = _walk_position(points, terminal.point_id, terminal.day_index)
    except StopIteration:
        # 当前点或终点不在这个模组版本的时间线上。这里不判断，交给
        # `next_point_after` 报 `time_next_point_not_found`。
        return False
    return current >= end


def next_point_after(
    module_content: ModuleContentV3,
    world_time: WorldTimeState,
) -> tuple[TimePointSpec, WorldTimePoint]:
    """The single point the room is allowed to enter next.

    Wrapping past the last point of the day rolls `day_index` forward: the cycle
    is `00 → 06 → 12 → 18 → next-day 00`, so the last point's successor is the
    first point of the following day.

    声明了 `terminal_point` 的模组走到那一刻之后就没有下一个点了：不再回卷，
    单夜模组因此不会"一觉睡到第二天"。
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

    if terminal_reached(module_content, world_time):
        raise ContractError(
            "terminal_point_reached: 已经到达模组时间线的终点，不能继续推进时间"
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
    """Pure resolution of one jump; committing it is the caller's transaction.

    这里同时把目标点声明的时段解析进运行态：谓词只拿得到 `GameState`，模组
    逐点声明的 `time_segment` 只能在这一刻落库（#415 §阶段一）。
    """

    target, moment = next_point_after(module_content, world_time)
    return WorldTimeState(
        current=moment,
        current_point_id=target.id,
        current_time_segment=target.resolved_segment,
    )


def player_time_label(module_content: ModuleContentV3, world_time: WorldTimeState) -> str:
    """玩家能看到的全部时间信息（#415 §阶段一）。

    模组逐点声明的 `label` 优先；没声明时按该点的 canonical segment 取缺省
    措辞。房间停在模组不再声明的点上（或阶段四的运行时临时点上）时，回退到
    运行态存下来的时段——那条路径拿不到 `TimePointSpec`，但玩家该看到的东西
    和精确小时无关，所以回退是安全的，不需要为它暴露 `hour_of_day`。
    """

    point = next(
        (
            item
            for item in module_content.time_policy.default_points
            if item.id == world_time.current_point_id
        ),
        None,
    )
    if point is not None:
        return point.resolved_label
    return default_label_for(world_time.time_segment)


def time_advance_block_reason(
    actor_ids: Sequence[str],
    *,
    module_content: ModuleContentV3 | None = None,
    world_time: WorldTimeState | None = None,
) -> TimeAdvanceBlockReason | None:
    """Why this room may not jump yet, or None when it may (#245 §四).

    Time is shared state: one investigator cannot sleep the whole party into
    the night. A solo room has nobody to disagree with, so consent is implicit
    and the jump proceeds. A party room needs an explicit readiness round,
    which is handled by the application layer's consent flow.

    终点优先于全员确认：多人房间在终点上根本不该创建提案，让玩家投完票才被拒
    是最难看的一种拒绝方式（#415 §阶段二）。

    `module_content` / `world_time` 可选，是为了让只关心"人多不多"的调用方不必
    先把模组读出来；不传就只判全员确认那一半。
    """

    if (
        module_content is not None
        and world_time is not None
        and terminal_reached(module_content, world_time)
    ):
        return TimeAdvanceBlockReason(
            code="terminal_point_reached",
            message="故事已经走到最后一个时间点，时间不会再推进了",
        )

    if len(actor_ids) <= 1:
        return None
    return TimeAdvanceBlockReason(
        code="time_advance_requires_party_ready",
        message="多人房间推进时间需要全体确认",
    )
