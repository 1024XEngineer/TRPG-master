"""离散时间线的顺序解析（#245 §一.1）。

时间不会流逝：没有计时器，行动不累加分钟，也不存在"推进 15 分钟"这种请求。
调用方只能说 advance_to_next，由时间线回答唯一的下一个点。
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from collaboration_framework.contracts import (
    DAY_SEGMENTS,
    NIGHT_SEGMENTS,
    ContractError,
    TimePointSpec,
    matches_time_query,
    segment_at_hour,
)
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.engine.models import WorldTimePoint, WorldTimeState
from collaboration_framework.engine.timeline import advanced_to_next, next_point_after

from tests.test_projection_v3 import module


class DiscreteTimelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.content = module()

    def at(self, point_id: str, *, day_index: int = 0, hour: int = 0) -> WorldTimeState:
        return WorldTimeState(
            current=WorldTimePoint(day_index=day_index, hour_of_day=hour),
            current_point_id=point_id,
        )

    def test_cycle_walks_the_module_declared_points(self) -> None:
        """《追书人》声明了自己的 time_policy，夜里多一个 20 点。

        20 点不是装饰：夜间监视和「睡到晚上八点再出门」都要落在一个真实存在的
        时间点上，否则 Agent 无从映射（见 module-content-v3.json time_policy）。
        """

        world = self.at("hour_00", hour=0)
        seen = []
        for _ in range(4):
            world = advanced_to_next(self.content, world)
            seen.append((world.current_point_id, world.current.day_index, world.current.hour_of_day))

        self.assertEqual(
            seen,
            [("hour_06", 0, 6), ("hour_12", 0, 12), ("hour_18", 0, 18), ("hour_20", 0, 20)],
        )

    def test_last_point_of_the_day_rolls_into_the_next_day(self) -> None:
        world = advanced_to_next(self.content, self.at("hour_20", hour=20))

        self.assertEqual(world.current_point_id, "hour_00")
        self.assertEqual(world.current.day_index, 1)
        self.assertEqual(world.current.hour_of_day, 0)

    def test_absolute_hour_orders_across_days(self) -> None:
        earlier = WorldTimePoint(day_index=0, hour_of_day=18)
        later = WorldTimePoint(day_index=1, hour_of_day=0)

        self.assertLess(earlier.absolute_hour, later.absolute_hour)

    def test_time_of_day_is_derived_not_stored(self) -> None:
        self.assertEqual(WorldTimePoint(hour_of_day=6).time_of_day, "day")
        self.assertEqual(WorldTimePoint(hour_of_day=17).time_of_day, "day")
        self.assertEqual(WorldTimePoint(hour_of_day=18).time_of_day, "night")
        self.assertEqual(WorldTimePoint(hour_of_day=5).time_of_day, "night")
        # 跨天不影响昼夜：只看小时。
        self.assertEqual(WorldTimePoint(day_index=3, hour_of_day=1).time_of_day, "night")

    def test_unknown_current_point_is_refused_rather_than_relocated(self) -> None:
        """房间停在这个模组版本已经不再声明的点上时，拒绝比"悄悄挪到别的小时"安全。"""

        with self.assertRaisesRegex(ContractError, "time_next_point_not_found"):
            next_point_after(self.content, self.at("hour_99", hour=9))

    def test_room_opens_on_the_declared_start_point(self) -> None:
        content = self.content.model_copy(
            update={
                "initial_state": self.content.initial_state.model_copy(
                    update={"start_time_point_id": "hour_18"}
                )
            },
            deep=True,
        )

        state = create_initial_game_state(content, room_id="room_01", actors={})

        self.assertEqual(state.world_time.current_point_id, "hour_18")
        self.assertEqual(state.world_time.current.hour_of_day, 18)
        self.assertEqual(state.world_time.time_of_day, "night")

    def test_module_without_a_declared_start_opens_on_the_first_point(self) -> None:
        """必须开在某个点"上"，否则之后每次跳转都没有可解析的起点。"""

        content = self.content.model_copy(
            update={
                "initial_state": self.content.initial_state.model_copy(
                    update={"start_time_point_id": None}
                )
            },
            deep=True,
        )

        state = create_initial_game_state(content, room_id="room_01", actors={})

        self.assertEqual(state.world_time.current_point_id, "hour_00")
        self.assertEqual(state.world_time.current.hour_of_day, 0)


class TimeSegmentDerivationTests(unittest.TestCase):
    """作者态的四段推导与查询别名（#415 §阶段一）。"""

    def test_canonical_segment_boundaries(self) -> None:
        self.assertEqual(
            [segment_at_hour(hour) for hour in (0, 5, 6, 11, 12, 17, 18, 23)],
            [
                "late_night",
                "late_night",
                "morning",
                "morning",
                "afternoon",
                "afternoon",
                "evening",
                "evening",
            ],
        )

    def test_hour_outside_the_day_is_refused_rather_than_clamped(self) -> None:
        with self.assertRaises(ValueError):
            segment_at_hour(24)

    def test_default_label_follows_the_derived_segment(self) -> None:
        point = TimePointSpec(id="hour_22", hour_of_day=22, order=0)

        self.assertEqual(point.resolved_segment, "evening")
        self.assertEqual(point.resolved_label, "晚上")

    def test_a_module_may_override_both_layers_per_point(self) -> None:
        """05:00 是黎明：规则按 morning/day 判断，玩家只看到「黎明」。

        硬编码 06–18 的旧推导会把它判成 night，这正是逐点覆盖要解决的事。
        """

        point = TimePointSpec(
            id="hour_05",
            hour_of_day=5,
            order=0,
            time_segment="morning",
            label="黎明",
        )

        self.assertEqual(point.resolved_segment, "morning")
        self.assertEqual(point.resolved_label, "黎明")
        self.assertTrue(matches_time_query(point.resolved_segment, "day"))

    def test_label_is_a_short_player_facing_phrase_not_prose(self) -> None:
        """长度上限让「把剧情正文塞进 label」在发布期失败，而不是在玩家屏幕上。"""

        with self.assertRaises(ValidationError):
            TimePointSpec(id="hour_22", hour_of_day=22, order=0, label="夜" * 21)

    def test_day_and_night_match_as_alias_sets(self) -> None:
        """追书人既有的 `time_of_day_is night` 因此不经迁移继续成立。"""

        self.assertEqual(DAY_SEGMENTS, {"morning", "afternoon"})
        self.assertEqual(NIGHT_SEGMENTS, {"evening", "late_night"})
        for segment in DAY_SEGMENTS:
            self.assertTrue(matches_time_query(segment, "day"))
            self.assertFalse(matches_time_query(segment, "night"))
        for segment in NIGHT_SEGMENTS:
            self.assertTrue(matches_time_query(segment, "night"))
            self.assertFalse(matches_time_query(segment, "day"))

    def test_a_four_segment_query_matches_exactly(self) -> None:
        """同为 night 的凌晨与晚上必须区分得开——这是布尔闩存在的原因。"""

        self.assertTrue(matches_time_query("evening", "evening"))
        self.assertFalse(matches_time_query("evening", "late_night"))
        self.assertFalse(matches_time_query("late_night", "evening"))

    def test_an_unknown_query_value_matches_nothing(self) -> None:
        self.assertFalse(matches_time_query("evening", "dusk"))
        self.assertFalse(matches_time_query("evening", None))


if __name__ == "__main__":
    unittest.main()
