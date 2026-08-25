"""定时任务的作者态契约与运行时模型（#245 §5 / #415 §阶段四）。

#245 冻结了这套形状，但 `RuntimeTimeTask` 一直不存在——只在
`engine/timeline.py` 的注释里被提过一次；`CreateTimeTaskStep` 也只有一个
`task_id`，没有目标时间，也就是说它根本无法实际创建任务。这里钉住补齐后的
形状，执行器是下一步的事。
"""

from __future__ import annotations

import unittest

from pydantic import ValidationError

from collaboration_framework.contracts import (
    CancelTimeTaskStep,
    CreateTimeTaskStep,
    TimeTaskSpec,
    TimeTaskTargetSpec,
)
from collaboration_framework.engine.models import (
    GameState,
    RuntimeTimeTask,
    TimePointOccurrence,
)


def task_spec(**overrides) -> TimeTaskSpec:
    base = {
        "task_key": "ghoul_arrives",
        "target": TimeTaskTargetSpec(day_index=0, hour_of_day=15),
        "on_due_branch_id": "on_due",
    }
    return TimeTaskSpec(**(base | overrides))


class TimeTaskTargetTests(unittest.TestCase):
    def test_a_default_point_target_needs_no_hour(self) -> None:
        """小时由 point_id 对应的 TimePointSpec 唯一确定，写两遍会自相矛盾。"""

        target = TimeTaskTargetSpec(point_id="hour_18")

        self.assertEqual(target.point_id, "hour_18")
        self.assertIsNone(target.hour_of_day)
        self.assertFalse(target.relative)

    def test_an_absolute_clock_target_needs_a_day(self) -> None:
        target = TimeTaskTargetSpec(day_index=1, hour_of_day=2)

        self.assertEqual((target.day_index, target.hour_of_day), (1, 2))

    def test_a_relative_target_is_an_offset_not_a_calendar_moment(self) -> None:
        """「三小时后」不需要知道今天是第几天。"""

        target = TimeTaskTargetSpec(hour_of_day=3, relative=True)

        self.assertTrue(target.relative)
        self.assertIsNone(target.day_index)

    def test_neither_or_both_addressing_modes_are_refused(self) -> None:
        for args in ({}, {"point_id": "hour_18", "hour_of_day": 15}):
            with self.subTest(args=args), self.assertRaisesRegex(ValidationError, "二选一"):
                TimeTaskTargetSpec(**args)

    def test_a_default_point_target_may_not_also_carry_a_day(self) -> None:
        with self.assertRaisesRegex(ValidationError, "不能再声明"):
            TimeTaskTargetSpec(point_id="hour_18", day_index=1)

    def test_an_absolute_target_without_a_day_is_refused(self) -> None:
        with self.assertRaisesRegex(ValidationError, "必须声明 day_index"):
            TimeTaskTargetSpec(hour_of_day=15)


class TimeTaskStepTests(unittest.TestCase):
    def test_create_carries_the_whole_task_not_just_an_id(self) -> None:
        step = CreateTimeTaskStep(
            id="schedule_ghoul",
            task=task_spec(priority=10, visibility="hidden"),
            next_step_id="finish",
        )

        self.assertEqual(step.task.task_key, "ghoul_arrives")
        self.assertEqual(step.task.target.hour_of_day, 15)
        self.assertEqual(step.task.priority, 10)
        self.assertEqual(step.task.visibility, "hidden")

    def test_cancel_locates_by_key_and_bindings_not_by_runtime_id(self) -> None:
        """规则写的时候还不知道运行时 id 长什么样。"""

        step = CancelTimeTaskStep(
            id="call_it_off",
            task_key="ghoul_arrives",
            bindings={"entity_id": "cemetery_figure"},
            reason_code="target_already_dead",
            next_step_id="finish",
        )

        self.assertEqual(step.task_key, "ghoul_arrives")
        self.assertEqual(step.bindings, {"entity_id": "cemetery_figure"})
        self.assertEqual(step.reason_code, "target_already_dead")

    def test_cancelling_without_a_reason_is_refused(self) -> None:
        with self.assertRaises(ValidationError):
            CancelTimeTaskStep(
                id="call_it_off",
                task_key="ghoul_arrives",
                reason_code="",
                next_step_id="finish",
            )


class RuntimeTimeModelTests(unittest.TestCase):
    def test_occurrences_order_by_absolute_hour_across_days(self) -> None:
        """默认点重复 occurrence 与剧情临时 occurrence 用同一套排序。"""

        temporary = TimePointOccurrence(
            occurrence_id="occ_15",
            day_index=0,
            hour_of_day=15,
            time_segment="afternoon",
        )
        next_day = TimePointOccurrence(
            occurrence_id="occ_d1_02",
            point_id="hour_02",
            day_index=1,
            hour_of_day=2,
            time_segment="late_night",
            origin="default",
        )

        self.assertLess(temporary.absolute_hour, next_day.absolute_hour)
        # 15:00 落在 12 与 18 之间，这就是临时点该插进去的位置。
        self.assertLess(12, temporary.hour_of_day)
        self.assertLess(temporary.hour_of_day, 18)

    def test_a_temporary_occurrence_names_no_module_point(self) -> None:
        """那条路径拿不到 TimePointSpec，玩家措辞只能回退到 segment 缺省值。"""

        occurrence = TimePointOccurrence(
            occurrence_id="occ_15",
            day_index=0,
            hour_of_day=15,
            time_segment="afternoon",
        )

        self.assertIsNone(occurrence.point_id)
        self.assertEqual(occurrence.origin, "time_task")

    def test_a_task_binds_to_an_occurrence_not_to_a_moment(self) -> None:
        """同日同小时的多个任务共享一个 occurrence，取消一个不影响其他。"""

        first = RuntimeTimeTask(
            task_id="task_a",
            task_key="ghoul_arrives",
            rule_id="night_watch",
            branch_id="on_due",
            occurrence_id="occ_15",
        )
        second = RuntimeTimeTask(
            task_id="task_b",
            task_key="letter_delivered",
            rule_id="postman",
            branch_id="on_due",
            occurrence_id="occ_15",
            priority=5,
        )

        self.assertEqual(first.occurrence_id, second.occurrence_id)
        self.assertEqual(first.status, "scheduled")
        # priority 再 task_id 是同点多任务的稳定顺序。
        first_due = min((second, first), key=lambda item: (item.priority, item.task_id))
        self.assertEqual(first_due.task_id, "task_a")

    def test_game_state_opens_with_no_tasks_and_no_temporary_points(self) -> None:
        state = GameState(room_id="room", scene_id="start", actors={}, entities={})

        self.assertEqual(state.time_tasks, {})
        self.assertEqual(state.time_occurrences, {})


if __name__ == "__main__":
    unittest.main()
