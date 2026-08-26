"""合法但不发布的时间线 fixture 模组（#415）。

已发布的两个模组覆盖不到本 Issue 的新能力：追书人是五点、无 label、无终点，
银之锁连 `time_policy` 都没声明。而「模组内容改版」不在 #415 范围内，所以真实
模组不能改。

这里造的是**合法可发布**的模组——`validate_module_v3_json` 判 pass，只是不进
`BUILTIN_MODULE_SPECS`、不进数据库。它还能覆盖真实模组永远不会有的形状：单夜
时间线、终点等于起点、只有 day/night 两个点。
"""

from __future__ import annotations

from collaboration_framework.contracts import (
    InitialStateSpec,
    LocationSpecV3,
    ModuleContentV3,
    ModulePresentation,
    ModuleStoryPage,
    ModuleTimePolicySpec,
    TerminalTimePointSpec,
    TimePointSpec,
)

# 《林隙的罪恶》那类单夜模组：整个故事发生在一夜之内。
#
# 声明顺序是**按小时升序**的 00/02/18/20/22，起点落在环上的 hour_18；走出来才是
# 18 → 20 → 22 → 次日 00 → 次日 02。把它写成「声明 18/20/22/00/02」会被
# `validate_points` 直接拒绝——那串本身不是升序（#415）。
SINGLE_NIGHT_POINTS: tuple[TimePointSpec, ...] = (
    TimePointSpec(id="hour_00", hour_of_day=0, order=0),
    TimePointSpec(id="hour_02", hour_of_day=2, order=1),
    TimePointSpec(id="hour_18", hour_of_day=18, order=2),
    TimePointSpec(id="hour_20", hour_of_day=20, order=3),
    # 22 点逐点覆盖玩家措辞：默认推导会说「晚上」，这个模组要说「深夜」。
    TimePointSpec(id="hour_22", hour_of_day=22, order=4, label="深夜"),
)

# 只有昼夜之分的模组：解析侧遇到原文只有 day/night 粒度时应当生成这两个点，
# 而不是把它们与默认四点合并——合并会让同一条 night 规则一天命中两次。
DAY_NIGHT_POINTS: tuple[TimePointSpec, ...] = (
    TimePointSpec(id="hour_06", hour_of_day=6, order=0),
    TimePointSpec(id="hour_18", hour_of_day=18, order=1),
)


def time_fixture_module(
    *,
    points: tuple[TimePointSpec, ...] = SINGLE_NIGHT_POINTS,
    start_point_id: str | None = "hour_18",
    terminal_point: TerminalTimePointSpec | None = None,
    module_id: str = "time-fixture",
) -> ModuleContentV3:
    """一个只为时间线存在的最小合法模组。

    刻意不带 information / entities / rules：这些集合与时间无关，带上只会让
    断言失败时要先排除无关噪声。地点保留一个，因为 `locations` 有 min_length=1。
    """

    return ModuleContentV3(
        module_id=module_id,
        version="1.0.0",
        world_ref="coc-7e",
        background="一个只为验证时间线而存在的模组。",
        locations=(
            LocationSpecV3(
                id="only_room",
                kind="room",
                name="唯一的房间",
                player_visible_name="唯一的房间",
                player_visible_description="时间线 fixture 用不到场景描述。",
            ),
        ),
        presentation=ModulePresentation(
            title="时间线 fixture",
            synopsis="不发布，只用于验证离散时间契约。",
            players_min=1,
            players_max=4,
            difficulty=1,
            estimated_duration="一夜",
            player_intro_pages=(
                ModuleStoryPage(content="夜色降临，故事在天亮前结束。"),
            ),
        ),
        initial_state=InitialStateSpec(
            start_location_id="only_room",
            start_time_point_id=start_point_id,
        ),
        time_policy=ModuleTimePolicySpec(
            default_points=points,
            terminal_point=terminal_point,
        ),
    )


def single_night_module() -> ModuleContentV3:
    """跨午夜的单夜模组，终点是 D1 02:00。

    起点 D0 18:00，走 4 跳到 D1 02:00 结束，再推就该被拒。
    """

    return time_fixture_module(
        terminal_point=TerminalTimePointSpec(point_id="hour_02", day_index=1),
    )


__all__ = [
    "DAY_NIGHT_POINTS",
    "SINGLE_NIGHT_POINTS",
    "single_night_module",
    "time_fixture_module",
]
