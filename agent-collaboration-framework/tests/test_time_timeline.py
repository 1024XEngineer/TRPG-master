"""离散时间线的顺序解析（#245 §一.1）。

时间不会流逝：没有计时器，行动不累加分钟，也不存在"推进 15 分钟"这种请求。
调用方只能说 advance_to_next，由时间线回答唯一的下一个点。
"""

from __future__ import annotations

import unittest

from collaboration_framework.contracts import ContractError
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

    def test_default_cycle_walks_00_06_12_18(self) -> None:
        world = self.at("hour_00", hour=0)
        seen = []
        for _ in range(3):
            world = advanced_to_next(self.content, world)
            seen.append((world.current_point_id, world.current.day_index, world.current.hour_of_day))

        self.assertEqual(
            seen,
            [("hour_06", 0, 6), ("hour_12", 0, 12), ("hour_18", 0, 18)],
        )

    def test_last_point_of_the_day_rolls_into_the_next_day(self) -> None:
        world = advanced_to_next(self.content, self.at("hour_18", hour=18))

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


if __name__ == "__main__":
    unittest.main()
