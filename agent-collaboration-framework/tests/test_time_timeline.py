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
    ModuleContentV3,
    ModuleTimePolicySpec,
    TerminalTimePointSpec,
    TimePointSpec,
    matches_time_query,
    segment_at_hour,
)
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.engine.models import (
    ActorState,
    EngineRuntimeSnapshot,
    WorldTimePoint,
    WorldTimeState,
)
from collaboration_framework.engine.projection_v3 import (
    keeper_capabilities_v3,
    project_v3,
)
from collaboration_framework.engine.timeline import (
    advanced_to_next,
    next_point_after,
    player_time_label,
    terminal_reached,
    time_advance_block_reason,
)
from tests.test_projection_v3 import ACTOR, module
from tests.time_fixtures import SINGLE_NIGHT_POINTS, single_night_module


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
            seen.append(
                (
                    world.current_point_id,
                    world.current.day_index,
                    world.current.hour_of_day,
                )
            )

        self.assertEqual(
            seen,
            [
                ("hour_06", 0, 6),
                ("hour_12", 0, 12),
                ("hour_18", 0, 18),
                ("hour_20", 0, 20),
            ],
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

    def test_advancing_resolves_the_declared_segment_into_the_state(self) -> None:
        """谓词拿不到 module_content，所以时段只能在推进这一刻落库。"""

        content = self.content.model_copy(
            update={
                "time_policy": self.content.time_policy.model_copy(
                    update={
                        "default_points": (
                            TimePointSpec(id="hour_00", hour_of_day=0, order=0),
                            # 05:00 声明成黎明：硬编码 06–18 的旧推导会判成 night。
                            TimePointSpec(
                                id="hour_05",
                                hour_of_day=5,
                                order=1,
                                time_segment="morning",
                                label="黎明",
                            ),
                        )
                    }
                )
            },
            deep=True,
        )

        world = advanced_to_next(content, self.at("hour_00", hour=0))

        self.assertEqual(world.current_point_id, "hour_05")
        self.assertEqual(world.current_time_segment, "morning")
        self.assertEqual(world.time_segment, "morning")

    def test_a_room_without_a_stored_segment_falls_back_to_the_hour(self) -> None:
        """既有房间的快照里没有这个字段，读取时回退，下一次推进后写入解析值。"""

        world = self.at("hour_18", hour=18)

        self.assertIsNone(world.current_time_segment)
        self.assertEqual(world.time_segment, "evening")
        self.assertEqual(WorldTimeState().time_segment, "afternoon")

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
        self.assertEqual(state.world_time.current_time_segment, "evening")

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


class TerminalTimePointTests(unittest.TestCase):
    """时间线的终点与推进边界（#415 §阶段二）。"""

    def walk(self, content, state, steps: int):
        seen = []
        for _ in range(steps):
            state = advanced_to_next(content, state)
            seen.append((state.current_point_id, state.current.day_index))
        return state, seen

    def test_a_single_night_module_walks_five_points_across_midnight(self) -> None:
        content = single_night_module()
        state = create_initial_game_state(
            content, room_id="room_01", actors={}
        ).world_time

        self.assertEqual(
            (state.current_point_id, state.current.day_index), ("hour_18", 0)
        )
        final, seen = self.walk(content, state, 4)

        self.assertEqual(
            seen,
            [("hour_20", 0), ("hour_22", 0), ("hour_00", 1), ("hour_02", 1)],
        )
        # 玩家依次看到 晚上 / 晚上 / 深夜 / 凌晨 / 凌晨。
        self.assertEqual(player_time_label(content, state), "晚上")
        self.assertEqual(player_time_label(content, final), "凌晨")

    def test_reaching_the_terminal_point_refuses_further_advance(self) -> None:
        content = single_night_module()
        state = create_initial_game_state(
            content, room_id="room_01", actors={}
        ).world_time
        final, _ = self.walk(content, state, 4)

        self.assertTrue(terminal_reached(content, final))
        with self.assertRaisesRegex(ContractError, "terminal_point_reached"):
            next_point_after(content, final)

    def test_the_ring_no_longer_wraps_into_a_repeating_night(self) -> None:
        """没有终点时走到 02:00 会回卷到 D1 18:00，夜晚无限重复。"""

        content = single_night_module()
        without_terminal = content.model_copy(
            update={
                "time_policy": content.time_policy.model_copy(
                    update={"terminal_point": None}
                )
            },
            deep=True,
        )
        at_end = WorldTimeState(
            current=WorldTimePoint(day_index=1, hour_of_day=2),
            current_point_id="hour_02",
        )

        wrapped = advanced_to_next(without_terminal, at_end)
        self.assertEqual(
            (wrapped.current_point_id, wrapped.current.day_index), ("hour_18", 1)
        )
        self.assertFalse(terminal_reached(without_terminal, at_end))

    def test_a_multi_day_module_only_stops_on_the_declared_occurrence(self) -> None:
        """第三天 18:00 结束：前两次进入 hour_18 仍可继续。"""

        content = module()
        content = content.model_copy(
            update={
                "time_policy": content.time_policy.model_copy(
                    update={
                        "terminal_point": TerminalTimePointSpec(
                            point_id="hour_18", day_index=2
                        )
                    }
                )
            },
            deep=True,
        )

        def at(point_id: str, day: int, hour: int) -> WorldTimeState:
            return WorldTimeState(
                current=WorldTimePoint(day_index=day, hour_of_day=hour),
                current_point_id=point_id,
            )

        self.assertFalse(terminal_reached(content, at("hour_18", 0, 18)))
        self.assertFalse(terminal_reached(content, at("hour_18", 1, 18)))
        self.assertTrue(terminal_reached(content, at("hour_18", 2, 18)))

    def test_a_room_that_somehow_overshot_the_terminal_fails_closed(self) -> None:
        """越过终点还能继续走，等于让时间线在作者没写过的地方跑。"""

        content = single_night_module()
        overshot = WorldTimeState(
            current=WorldTimePoint(day_index=3, hour_of_day=20),
            current_point_id="hour_20",
        )

        self.assertTrue(terminal_reached(content, overshot))
        with self.assertRaisesRegex(ContractError, "terminal_point_reached"):
            next_point_after(content, overshot)

    def test_block_reason_carries_a_stable_code_not_a_parsed_string(self) -> None:
        content = single_night_module()
        state = create_initial_game_state(
            content, room_id="room_01", actors={}
        ).world_time
        final, _ = self.walk(content, state, 4)

        blocked = time_advance_block_reason(
            ("actor_1",), module_content=content, world_time=final
        )
        assert blocked is not None
        self.assertEqual(blocked.code, "terminal_point_reached")
        # 单人房间在终点之前没有任何阻塞。
        self.assertIsNone(
            time_advance_block_reason(
                ("actor_1",), module_content=content, world_time=state
            )
        )

    def test_the_terminal_outranks_the_party_consent_round(self) -> None:
        """多人房间在终点根本不该创建提案，让玩家投完票才被拒最难看。"""

        content = single_night_module()
        state = create_initial_game_state(
            content, room_id="room_01", actors={}
        ).world_time
        final, _ = self.walk(content, state, 4)

        blocked = time_advance_block_reason(
            ("actor_1", "actor_2"), module_content=content, world_time=final
        )
        assert blocked is not None
        self.assertEqual(blocked.code, "terminal_point_reached")

    def test_a_terminal_before_the_opening_moment_is_refused_at_publish(self) -> None:
        """18:00 开局配「第一天 00:00 结束」不可达——那一刻在开局之前。

        校验只能落在根上：终点声明在 `time_policy` 里，开局时刻在
        `initial_state` 里，`ModuleTimePolicySpec` 自己看不到后者。
        """

        payload = single_night_module().model_dump(mode="json")
        payload["time_policy"]["terminal_point"] = {
            "point_id": "hour_00",
            "day_index": 0,
        }

        with self.assertRaisesRegex(ValidationError, "不可达"):
            ModuleContentV3.model_validate(payload)

    def test_the_same_terminal_one_day_later_is_reachable(self) -> None:
        """回卷之后的 D1 00:00 就在 walk 上，只有 D0 那一次不在。"""

        payload = single_night_module().model_dump(mode="json")
        payload["time_policy"]["terminal_point"] = {
            "point_id": "hour_00",
            "day_index": 1,
        }

        content = ModuleContentV3.model_validate(payload)
        self.assertEqual(content.time_policy.terminal_point.point_id, "hour_00")

    def snapshot(self, content, world_time):
        state = create_initial_game_state(
            content,
            room_id="room_01",
            actors={
                ACTOR: ActorState(
                    player_id="player_1",
                    name="陈探员",
                    source_character_id="character_v3",
                    source_character_version=1,
                )
            },
        )
        return EngineRuntimeSnapshot(
            module_id=content.module_id,
            module_version=content.version,
            module_content=content,
            game_state=state.model_copy(update={"world_time": world_time}, deep=True),
            revision="1",
        )

    def test_keeper_sees_no_next_point_and_a_structured_reason_at_the_end(self) -> None:
        content = single_night_module()
        start = create_initial_game_state(
            content, room_id="room_01", actors={}
        ).world_time
        final, _ = self.walk(content, start, 4)

        before = keeper_capabilities_v3(
            self.snapshot(content, start), actor_id=ACTOR
        ).time
        after = keeper_capabilities_v3(
            self.snapshot(content, final), actor_id=ACTOR
        ).time
        assert before is not None and after is not None

        self.assertEqual(before.next_point_id, "hour_20")
        self.assertIsNone(before.blocked_reason)
        # 精确时刻在 Keeper 侧照常保留，收窄的只是玩家侧投影。
        self.assertEqual(after.current_hour_of_day, 2)
        self.assertEqual(after.current_day_index, 1)
        self.assertIsNone(after.next_point_id)
        assert after.blocked_reason is not None
        self.assertEqual(after.blocked_reason.code, "terminal_point_reached")

    def test_players_only_learn_that_the_button_is_dead(self) -> None:
        """玩家侧只投 can_advance_time，看不到终点是哪个点、哪一刻。"""

        content = single_night_module()
        start = create_initial_game_state(
            content, room_id="room_01", actors={}
        ).world_time
        final, _ = self.walk(content, start, 4)

        before = project_v3(
            self.snapshot(content, start), player_id="player_1", actor_id=ACTOR
        ).world
        after = project_v3(
            self.snapshot(content, final), player_id="player_1", actor_id=ACTOR
        ).world

        self.assertTrue(before.can_advance_time)
        self.assertFalse(after.can_advance_time)
        # 终点不自动结束游戏。
        self.assertFalse(after.core_resolved)
        self.assertIsNone(after.ending_id)

    def test_a_terminal_naming_an_undeclared_point_is_refused(self) -> None:
        with self.assertRaisesRegex(ValidationError, "不存在的时间点"):
            ModuleTimePolicySpec(
                default_points=SINGLE_NIGHT_POINTS,
                terminal_point=TerminalTimePointSpec(point_id="hour_99", day_index=1),
            )


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

    def test_hours_outside_the_day_are_refused_at_both_ends(self) -> None:
        """只查上界的话 -1 会安静地变成凌晨；这个函数是公共导出的。"""

        for hour in (-1, -24, 24, 99):
            with self.subTest(hour=hour), self.assertRaises(ValueError):
                segment_at_hour(hour)

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
