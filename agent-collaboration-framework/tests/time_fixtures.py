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
    EntitySpecV3,
    InitialStateSpec,
    LocationSpecV3,
    ModuleContentV3,
    ModulePresentation,
    ModuleStoryPage,
    ModuleTimePolicySpec,
    RuleSpecV3,
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

# 昼夜循环：00 / 06 / 12 / 18 / 20，正午开局。
#
# 这个形状此前是《追书人》替引擎测试兼职提供的——它当时恰好声明了这五个点，于是
# 时间线、定时任务、事件屏障几组测试都直接读真实模组文件，并把 `hour_12` /
# `hour_20` / `hour_00` 写死进断言。#451 把《追书人》收敛成昼夜两点之后，23 条引擎
# 测试一起断掉：它们测的是引擎，却把模组内容当成了稳定契约。
#
# 形状本身有存在价值，所以搬到这里由 fixture 自己拥有：正午开局让「三小时后」落在
# 15:00 这样的空档上，18/20/00 三个连续夜点让「同一条夜间规则会不会被跑三次」有地
# 方可问。模组再怎么改版都不会再碰它。
DAY_CYCLE_POINTS: tuple[TimePointSpec, ...] = (
    TimePointSpec(id="hour_00", hour_of_day=0, order=0),
    TimePointSpec(id="hour_06", hour_of_day=6, order=1),
    TimePointSpec(id="hour_12", hour_of_day=12, order=2),
    TimePointSpec(id="hour_18", hour_of_day=18, order=3),
    TimePointSpec(id="hour_20", hour_of_day=20, order=4),
)

# 一个可写状态的实体：规则要留下痕迹，断言才有东西可看。
TRACKER_ENTITY = EntitySpecV3(
    id="case_tracker",
    kind="object",
    name="进度记录",
    state={"night_seen": False},
)

# 夜间闩规则：进入夜里翻一次开关，条件自己保证只翻一次。
#
# 事件屏障要问的是「事件规则按**它自己那条事件**当时的世界匹配，而不是按整段效果
# 跑完后的终态」。要问得出来，就需要一条只在夜里成立、且自带幂等前置条件的规则——
# 从正午一路睡到次日早晨会连跨 18 / 20 / 00 三个夜点，终态却是 06:00 的白天。
NIGHT_LATCH_RULE = RuleSpecV3.model_validate(
    {
        "id": "night_latch",
        "priority": 30,
        "trigger": {
            "kind": "event",
            "event_type": "time.point_entered",
            "when": {
                "op": "all",
                "items": [
                    {
                        "op": "predicate",
                        "predicate": "time_of_day_is",
                        "args": {"value": "night"},
                    },
                    {
                        "op": "predicate",
                        "predicate": "entity_state_is",
                        "args": {
                            "entity_id": "case_tracker",
                            "key": "night_seen",
                            "value": False,
                        },
                    },
                ],
            },
            "entry_branch_id": "default",
        },
        "execution": {
            "branches": [{"id": "default", "entry_step_id": "mark"}],
            "steps": [
                {
                    "id": "mark",
                    "kind": "effect",
                    "effect": {
                        "type": "change_entity_state",
                        "entity_id": "case_tracker",
                        "key": "night_seen",
                        "value": True,
                    },
                    "next_step_id": "finish",
                },
                {"id": "finish", "kind": "finish"},
            ],
        },
    }
)


def time_fixture_module(
    *,
    points: tuple[TimePointSpec, ...] = SINGLE_NIGHT_POINTS,
    start_point_id: str | None = "hour_18",
    terminal_point: TerminalTimePointSpec | None = None,
    module_id: str = "time-fixture",
    entities: tuple[EntitySpecV3, ...] = (),
    rules: tuple[RuleSpecV3, ...] = (),
) -> ModuleContentV3:
    """一个只为时间线存在的最小合法模组。

    默认不带 information / entities / rules：这些集合与时间无关，带上只会让断言
    失败时要先排除无关噪声。地点保留一个，因为 `locations` 有 min_length=1。

    `entities` / `rules` 是给「规则跨时间点触发」那几组测试开的口子：它们必须有
    一条真规则和一个可写实体才问得出问题，而在此之前唯一的来源是读《追书人》的
    真实内容——模组一改版测试就断。默认值保持空，所以纯时间线测试看到的形状与
    以前一致。
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
        entities=entities,
        rules=rules,
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


def day_cycle_module(**overrides) -> ModuleContentV3:
    """`DAY_CYCLE_POINTS` 上的正午开局模组，带一个可写实体。

    引擎侧的时间线 / 定时任务 / 事件屏障测试都以它为底：形状与《追书人》改版前
    一致，所以那些测试的语义原样保留，只是不再读真实模组文件。需要规则的测试自己
    传 `rules=`——默认不带，免得纯时间线断言要先排除规则噪声。
    """

    return time_fixture_module(
        points=DAY_CYCLE_POINTS,
        start_point_id="hour_12",
        entities=(TRACKER_ENTITY,),
        module_id="day-cycle-fixture",
        **overrides,
    )


__all__ = [
    "DAY_CYCLE_POINTS",
    "DAY_NIGHT_POINTS",
    "NIGHT_LATCH_RULE",
    "SINGLE_NIGHT_POINTS",
    "TRACKER_ENTITY",
    "day_cycle_module",
    "single_night_module",
    "time_fixture_module",
]
