"""Ordered discrete timeline: where the room may jump to next (#245 §一.1).

The whole point of the discrete model is that "what time is it next" is an
authoritative, deterministic lookup rather than arithmetic on a duration. Callers
never say *how far* to advance; they say `advance_to_next` and the timeline
answers with exactly one point.

Scope note: this module resolves **default** points only. Story temporary points
(§一.5) insert extra occurrences between two default points; the models exist
(`TimePointOccurrence` / `RuntimeTimeTask`) but the executor that creates them
does not yet — until it does, `ordered_points` sees only what the module
declared.
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

from .models import TimePointOccurrence, WorldTimePoint, WorldTimeState


def occurrence_id_for(moment: WorldTimePoint) -> str:
    """这一刻对应的 occurrence id。

    默认点与剧情临时点共用同一个公式，所以同日同小时的任务必然落在同一个
    occurrence 上——任务之间共享点、取消互不影响，靠的就是这一条。

    它同时是「房间现在站在哪」的身份依据：`current_point_id` 恰好等于当前时刻
    minted 出来的 id 时，说明房间站在一个引擎自己排出来的临时点上；否则那就是
    模组换版后失效的点，必须拒绝而不是悄悄挪走队伍。
    """

    return f"occ_d{moment.day_index}_h{moment.hour_of_day:02d}"


def ordered_points(module_content: ModuleContentV3) -> tuple[TimePointSpec, ...]:
    """模组声明的默认点，按 `order`（也就是环上的位置）排序。

    只有默认点。剧情临时点是运行态，由 `next_point_after` 在解析下一跳时合并
    进来——它们不属于模组内容，混进这里会让「模组声明了哪些点」这个问题变得
    依赖房间状态。
    """

    return tuple(sorted(module_content.time_policy.default_points, key=lambda item: item.order))


def terminal_reached(
    module_content: ModuleContentV3,
    world_time: WorldTimeState,
) -> bool:
    """房间是否已经走到（或越过）模组声明的最后一刻。

    比较走绝对时刻。环是按小时升序声明的，`order` 随小时单调，越过末点才进位，
    所以「(day_index, order) 的字典序」与「absolute_hour 的大小」是同一个序 ——
    用后者少一次查表，还顺带覆盖了「房间正站在剧情临时点上」这种 order 根本不
    存在的情况。

    越过也算：异常状态下 fail closed 比继续推进安全——已经越过终点还能往前走，
    等于让时间线在作者根本没写过的地方继续跑。

    没声明终点的模组永远返回 False，维持现有环形回卷。
    """

    terminal = module_content.time_policy.terminal_point
    if terminal is None:
        return False

    point = next(
        (
            item
            for item in ordered_points(module_content)
            if item.id == terminal.point_id
        ),
        None,
    )
    if point is None:
        # 终点引用的点不在这个模组版本里。发布期校验拦得住，运行期遇到只能
        # 交给 `next_point_after` 报 time_next_point_not_found。
        return False
    return world_time.current.absolute_hour >= terminal.day_index * 24 + point.hour_of_day


def next_point_after(
    module_content: ModuleContentV3,
    world_time: WorldTimeState,
    occurrences: Sequence[TimePointOccurrence] = (),
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
    if index is None and world_time.current_point_id != occurrence_id_for(
        world_time.current
    ):
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

    target, moment = _next_default_point(points, index, world_time.current)

    # 剧情临时点插在两个默认点之间：如果还有任务等在「现在」和「默认的下一
    # 跳」之间，那一刻才是真正的下一跳（#245 §一.5 / #415 §阶段四）。
    pending = _earliest_pending_occurrence(
        occurrences,
        after=world_time.current.absolute_hour,
        before=moment.absolute_hour,
    )
    if pending is not None:
        return (
            TimePointSpec(
                id=pending.occurrence_id,
                hour_of_day=pending.hour_of_day,
                # 临时点不在环上，`order` 只是为了满足契约；排序走的是绝对
                # 时刻，不是这个字段。
                order=0,
                time_segment=pending.time_segment,
            ),
            WorldTimePoint(day_index=pending.day_index, hour_of_day=pending.hour_of_day),
        )
    return target, moment


def _next_default_point(
    points: Sequence[TimePointSpec],
    index: int | None,
    now: WorldTimePoint,
) -> tuple[TimePointSpec, WorldTimePoint]:
    """环上的下一个默认点。

    `index` 是当前点在环上的位置；房间站在剧情临时点上时它是 None ——那种点
    不在环上，没有「下一个 order」可言，只能按当前绝对时刻重新定位：同一天里
    第一个更晚的点，没有就回卷到次日的首点。

    两条路算出来的是同一个东西：点按小时升序声明，所以「order + 1」和「第一个
    更晚的小时」在环上指的是同一个位置。临时点只是没有 order 而已。
    """

    if index is not None:
        following = index + 1
        if following < len(points):
            return points[following], WorldTimePoint(
                day_index=now.day_index, hour_of_day=points[following].hour_of_day
            )
        return points[0], WorldTimePoint(
            day_index=now.day_index + 1, hour_of_day=points[0].hour_of_day
        )

    later = next((item for item in points if item.hour_of_day > now.hour_of_day), None)
    if later is not None:
        return later, WorldTimePoint(
            day_index=now.day_index, hour_of_day=later.hour_of_day
        )
    return points[0], WorldTimePoint(
        day_index=now.day_index + 1, hour_of_day=points[0].hour_of_day
    )


def _earliest_pending_occurrence(
    occurrences: Sequence[TimePointOccurrence],
    *,
    after: int,
    before: int,
) -> TimePointOccurrence | None:
    """严格落在这两个绝对时刻之间的最早那个临时点。

    两端都是开区间：等于 `after` 的点就是现在，已经到过了；等于 `before` 的
    点和默认的下一跳同刻，绑的是那个点本身，不需要额外插一次。
    """

    candidates = [item for item in occurrences if after < item.absolute_hour < before]
    if not candidates:
        return None
    return min(candidates, key=lambda item: item.absolute_hour)


def advanced_to_next(
    module_content: ModuleContentV3,
    world_time: WorldTimeState,
    occurrences: Sequence[TimePointOccurrence] = (),
) -> WorldTimeState:
    """Pure resolution of one jump; committing it is the caller's transaction.

    这里同时把目标点声明的时段解析进运行态：谓词只拿得到 `GameState`，模组
    逐点声明的 `time_segment` 只能在这一刻落库（#415 §阶段一）。
    """

    target, moment = next_point_after(module_content, world_time, occurrences)
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
