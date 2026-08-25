"""定时任务的作者态契约与运行时模型（#245 §5 / #415 §阶段四）。

#245 冻结了这套形状，但 `RuntimeTimeTask` 一直不存在——只在
`engine/timeline.py` 的注释里被提过一次；`CreateTimeTaskStep` 也只有一个
`task_id`，没有目标时间，也就是说它根本无法实际创建任务。这里钉住补齐后的
形状，执行器是下一步的事。
"""

from __future__ import annotations

import json
import unittest

from pydantic import ValidationError

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdvanceWorldTimeEffect,
    CancelTimeTaskStep,
    ContractError,
    CreateTimeTaskStep,
    ModuleContentV3,
    NoAdjudicationCheck,
    RuleSpecV3,
    SubmitAdjudicationRequest,
    TerminalTimePointSpec,
    TimeTaskSpec,
    TimeTaskTargetSpec,
)
from collaboration_framework.engine import (
    AdjudicationEngineService,
    InMemoryEngineStore,
)
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.engine.models import (
    EngineRuntimeSnapshot,
    GameState,
    RuntimeTimeTask,
    TimePointOccurrence,
    WorldTimePoint,
    WorldTimeState,
)
from collaboration_framework.engine.projection_v3 import project_v3
from collaboration_framework.engine.time_tasks import (
    active_occurrences,
    cancel_time_task,
    create_time_task,
    due_tasks,
    resolve_target,
    settle_due_tasks,
)
from collaboration_framework.engine.timeline import next_point_after, player_time_label
from tests.test_projection_v3 import ACTOR, PLAYER, ROOM, game_state, module


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


class TimeTaskExecutorTests(unittest.TestCase):
    """排定 / 取消与临时点排序（#415 §阶段四）。"""

    def setUp(self) -> None:
        # 追书人声明了 00 / 06 / 12 / 18 / 20，房间从 hour_12 开局。
        self.content = module()
        self.state = create_initial_game_state(self.content, room_id="room_01", actors={})

    def create(self, state, target, **overrides):
        step = CreateTimeTaskStep(
            id="schedule",
            task=task_spec(target=target, **overrides),
            next_step_id="finish",
        )
        return create_time_task(self.content, state, step, rule_id="night_watch")

    def test_a_target_between_two_default_points_inserts_a_temporary_one(self) -> None:
        """15:00 落在 12 与 18 之间，作者没声明过它。"""

        state, task, occurrence = self.create(
            self.state, TimeTaskTargetSpec(day_index=0, hour_of_day=15)
        )

        assert occurrence is not None
        self.assertIsNone(occurrence.point_id)
        self.assertEqual((occurrence.day_index, occurrence.hour_of_day), (0, 15))
        self.assertEqual(occurrence.time_segment, "afternoon")
        self.assertEqual(task.occurrence_id, occurrence.occurrence_id)

        # 下一跳因此不是 18:00，而是插进来的 15:00。
        target, moment = next_point_after(
            self.content, state.world_time, active_occurrences(state)
        )
        self.assertEqual((moment.day_index, moment.hour_of_day), (0, 15))
        self.assertEqual(target.id, occurrence.occurrence_id)

    def test_a_target_that_is_already_a_default_point_creates_no_duplicate(self) -> None:
        state, task, occurrence = self.create(
            self.state, TimeTaskTargetSpec(point_id="hour_18")
        )

        self.assertIsNone(occurrence)
        self.assertEqual(state.time_occurrences, {})
        # 任务照样绑得上：那一刻由默认点本身提供。
        self.assertEqual(task.status, "scheduled")
        target, moment = next_point_after(
            self.content, state.world_time, active_occurrences(state)
        )
        self.assertEqual(target.id, "hour_18")
        self.assertEqual(moment.hour_of_day, 18)

    def test_two_tasks_at_the_same_moment_share_one_occurrence(self) -> None:
        state, first, created = self.create(
            self.state, TimeTaskTargetSpec(day_index=0, hour_of_day=15)
        )
        state, second, again = self.create(
            state,
            TimeTaskTargetSpec(day_index=0, hour_of_day=15),
            task_key="letter_delivered",
        )

        assert created is not None
        self.assertIsNone(again)
        self.assertEqual(first.occurrence_id, second.occurrence_id)
        self.assertEqual(len(state.time_occurrences), 1)
        self.assertEqual(len(due_tasks(state, first.occurrence_id)), 2)

    def test_cancelling_one_task_leaves_the_others_and_their_point_alone(self) -> None:
        state, first, _ = self.create(
            self.state, TimeTaskTargetSpec(day_index=0, hour_of_day=15)
        )
        state, second, _ = self.create(
            state,
            TimeTaskTargetSpec(day_index=0, hour_of_day=15),
            task_key="letter_delivered",
        )

        state, cancelled = cancel_time_task(
            state,
            CancelTimeTaskStep(
                id="call_off",
                task_key="ghoul_arrives",
                reason_code="target_already_dead",
                next_step_id="finish",
            ),
            rule_id="night_watch",
        )

        assert cancelled is not None
        self.assertEqual(cancelled.status, "cancelled")
        self.assertEqual(cancelled.cancel_reason_code, "target_already_dead")
        # 点还在，因为 second 还等着。
        self.assertIn(first.occurrence_id, state.time_occurrences)
        self.assertEqual(due_tasks(state, first.occurrence_id), (second,))

    def test_the_point_goes_away_once_its_last_task_is_cancelled(self) -> None:
        state, task, _ = self.create(
            self.state, TimeTaskTargetSpec(day_index=0, hour_of_day=15)
        )
        state, _ = cancel_time_task(
            state,
            CancelTimeTaskStep(
                id="call_off",
                task_key="ghoul_arrives",
                reason_code="player_intervened",
                next_step_id="finish",
            ),
            rule_id="night_watch",
        )

        self.assertEqual(state.time_occurrences, {})
        # 时间线回到原样：下一跳又是 18:00。
        target, _ = next_point_after(self.content, state.world_time, active_occurrences(state))
        self.assertEqual(target.id, "hour_18")
        del task

    def test_cancelling_something_that_is_not_scheduled_is_not_an_error(self) -> None:
        """规则可能在两条路径上都写了取消，先到的那条已经做完了。"""

        state, cancelled = cancel_time_task(
            self.state,
            CancelTimeTaskStep(
                id="call_off",
                task_key="never_scheduled",
                reason_code="whatever",
                next_step_id="finish",
            ),
            rule_id="night_watch",
        )

        self.assertIsNone(cancelled)
        self.assertEqual(state.time_tasks, {})

    def test_rescheduling_the_same_task_is_idempotent(self) -> None:
        """id 从 rule + key + bindings 推导，重试不该排出第二个一模一样的任务。"""

        state, first, _ = self.create(
            self.state, TimeTaskTargetSpec(day_index=0, hour_of_day=15)
        )
        state, again, created = self.create(
            state, TimeTaskTargetSpec(day_index=0, hour_of_day=15)
        )

        self.assertEqual(first.task_id, again.task_id)
        self.assertIsNone(created)
        self.assertEqual(len(state.time_tasks), 1)

    def test_a_relative_target_counts_from_the_current_clock(self) -> None:
        state, task, occurrence = self.create(
            self.state, TimeTaskTargetSpec(hour_of_day=3, relative=True)
        )

        assert occurrence is not None
        # 从 D0 12:00 起算三小时。
        self.assertEqual((occurrence.day_index, occurrence.hour_of_day), (0, 15))
        del state, task

    def test_binding_a_default_point_takes_its_next_arrival_not_a_past_one(self) -> None:
        """「18 点」在 20:00 说出来指的是明天那一次，不是已经过去的今天。"""

        evening = self.state.model_copy(
            update={
                "world_time": WorldTimeState(
                    current=WorldTimePoint(day_index=0, hour_of_day=20),
                    current_point_id="hour_20",
                    current_time_segment="evening",
                )
            },
            deep=True,
        )

        moment = resolve_target(self.content, evening, TimeTaskTargetSpec(point_id="hour_18"))

        self.assertEqual((moment.day_index, moment.hour_of_day), (1, 18))

    def test_a_target_past_the_terminal_point_is_refused_at_creation(self) -> None:
        """越界任务永远不会到期，留着就是一条静默失效的剧情线。"""

        content = self.content.model_copy(
            update={
                "time_policy": self.content.time_policy.model_copy(
                    update={
                        "terminal_point": TerminalTimePointSpec(
                            point_id="hour_20", day_index=0
                        )
                    }
                )
            },
            deep=True,
        )
        step = CreateTimeTaskStep(
            id="schedule",
            task=task_spec(target=TimeTaskTargetSpec(day_index=1, hour_of_day=6)),
            next_step_id="finish",
        )

        with self.assertRaisesRegex(ContractError, "invalid_time_task_target"):
            create_time_task(content, self.state, step, rule_id="night_watch")

    def test_a_target_exactly_on_the_terminal_point_is_allowed(self) -> None:
        content = self.content.model_copy(
            update={
                "time_policy": self.content.time_policy.model_copy(
                    update={
                        "terminal_point": TerminalTimePointSpec(
                            point_id="hour_20", day_index=0
                        )
                    }
                )
            },
            deep=True,
        )
        step = CreateTimeTaskStep(
            id="schedule",
            task=task_spec(target=TimeTaskTargetSpec(point_id="hour_20")),
            next_step_id="finish",
        )

        _, task, _ = create_time_task(content, self.state, step, rule_id="night_watch")

        self.assertEqual(task.status, "scheduled")

    def test_due_tasks_are_ordered_by_priority_then_id(self) -> None:
        """顺序必须稳定，否则断线恢复重放出来的世界和第一次跑出来的不一样。"""

        state, _, _ = self.create(
            self.state, TimeTaskTargetSpec(day_index=0, hour_of_day=15), priority=9
        )
        state, low, _ = self.create(
            state,
            TimeTaskTargetSpec(day_index=0, hour_of_day=15),
            task_key="letter_delivered",
            priority=1,
        )

        ordered = due_tasks(state, low.occurrence_id)

        self.assertEqual([item.priority for item in ordered], [1, 9])


class TimeTaskThroughARuleTests(unittest.IsolatedAsyncioTestCase):
    """执行器要真的接在 RuleAgenda 上，不只是能被直接调用（#415 §阶段四）。"""

    def module_with_scheduling_rule(self) -> ModuleContentV3:
        """给追书人加一条规则：进入 18:00 时排一个 21:00 的任务。

        21:00 不在模组声明的 00/06/12/18/20 里，所以它必须插一个临时点。
        """

        content = module()
        rule = RuleSpecV3.model_validate(
            {
                "id": "schedule_late_visitor",
                "priority": 90,
                "trigger": {
                    "kind": "event",
                    "event_type": "time.point_entered",
                    "when": {
                        "op": "predicate",
                        "predicate": "time_point_is",
                        "args": {"value": "hour_18"},
                    },
                    "entry_branch_id": "default",
                },
                "execution": {
                    "branches": [{"id": "default", "entry_step_id": "schedule"}],
                    "steps": [
                        {
                            "id": "schedule",
                            "kind": "create_time_task",
                            "task": {
                                "task_key": "late_visitor",
                                "target": {"day_index": 0, "hour_of_day": 21},
                                "on_due_branch_id": "default",
                            },
                            "next_step_id": "finish",
                        },
                        {"id": "finish", "kind": "finish"},
                    ],
                },
            }
        )
        return content.model_copy(update={"rules": (*content.rules, rule)}, deep=True)

    def submit(self, engine, *points, request_id, store=None):
        # revision 从状态里读，不要写死 "0"：第二次提交时它已经推进过了。
        revision = "0" if store is None else str(store.inspect_state(ROOM).event_sequence)
        return engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id=request_id,
                    source_revision=revision,
                    actor_id=ACTOR,
                    summary="等到入夜",
                    target=ActionTarget(kind="location", id="thomas_office"),
                    method=ActionMethod(family="rest", description="等待"),
                    check=NoAdjudicationCheck(),
                    success_effects=tuple(
                        AdvanceWorldTimeEffect(to_point_id=point) for point in points
                    ),
                ),
            )
        )

    async def test_a_rule_schedules_a_task_and_keeps_walking(self) -> None:
        content = self.module_with_scheduling_rule()
        store = InMemoryEngineStore()
        store.register_room(module_content=content, initial_state=game_state(content))
        engine = AdjudicationEngineService(store)

        execution = await self.submit(engine, "hour_18", request_id="wait-until-evening")

        # 规则跑完了整条链，没有停在「无执行器的挂起点」上。
        self.assertEqual(execution.status, "resolved")
        state = store.inspect_state(ROOM)

        scheduled = [task for task in state.time_tasks.values() if task.status == "scheduled"]
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0].task_key, "late_visitor")

        # 21:00 插在 20:00 和次日 00:00 之间。
        occurrence = state.time_occurrences[scheduled[0].occurrence_id]
        self.assertEqual((occurrence.day_index, occurrence.hour_of_day), (0, 21))
        self.assertEqual(occurrence.origin, "time_task")

        scheduled_events = [
            event
            for event in store.inspect_domain_events(ROOM)
            if event.type == "time.task_scheduled"
        ]
        self.assertEqual(len(scheduled_events), 1)
        self.assertTrue(scheduled_events[0].payload["created_occurrence"])

    async def test_the_temporary_point_becomes_the_next_jump(self) -> None:
        """20:00 之后本该是次日 00:00，21:00 的任务把它挤到后面去。"""

        content = self.module_with_scheduling_rule()
        store = InMemoryEngineStore()
        store.register_room(module_content=content, initial_state=game_state(content))
        engine = AdjudicationEngineService(store)

        await self.submit(engine, "hour_18", "hour_20", request_id="wait-until-eight")

        state = store.inspect_state(ROOM)
        self.assertEqual(state.world_time.current_point_id, "hour_20")

        _, moment = next_point_after(content, state.world_time, active_occurrences(state))

        self.assertEqual((moment.day_index, moment.hour_of_day), (0, 21))

    async def test_advancing_actually_enters_the_temporary_point(self) -> None:
        """临时点必须走通真实的推进路径，不能只在 next_point_after 里存在。

        `advance_world_time` 的 to_point_id 要逐字等于下一跳的 id，而插进来的
        那一跳的 id 就是 occurrence_id——所以这里也顺带钉住了 Agent 拿到的
        `next_point_id` 与 Engine 接受的目标是同一个东西。
        """

        content = self.module_with_scheduling_rule()
        store = InMemoryEngineStore()
        store.register_room(module_content=content, initial_state=game_state(content))
        engine = AdjudicationEngineService(store)

        await self.submit(engine, "hour_18", "hour_20", request_id="wait-until-eight")
        state = store.inspect_state(ROOM)
        occurrence_id = next(iter(state.time_occurrences))

        await self.submit(
            engine, occurrence_id, request_id="wait-a-bit-longer", store=store
        )

        after = store.inspect_state(ROOM)
        self.assertEqual(after.world_time.current_point_id, occurrence_id)
        self.assertEqual(after.world_time.current.hour_of_day, 21)
        self.assertEqual(after.world_time.current.day_index, 0)
        # 临时点没有 TimePointSpec，玩家措辞回退到 segment 的缺省值。
        self.assertEqual(after.world_time.current_time_segment, "evening")
        self.assertEqual(player_time_label(content, after.world_time), "晚上")


class TaskDueTests(unittest.IsolatedAsyncioTestCase):
    """到期结算：单次发布、稳定顺序、隐藏边界（#415 §阶段四）。"""

    def module_with_due_rule(self) -> ModuleContentV3:
        """21:00 排一个任务，到期时把 case_tracker 上的一个标记翻真。

        规则的入口分支故意写成 `never`，任务声明的是 `on_due`——只有
        `on_due_branch_id` 被真正采纳，标记才会翻。
        """

        content = module()
        scheduler = RuleSpecV3.model_validate(
            {
                "id": "schedule_late_visitor",
                "priority": 90,
                "trigger": {
                    "kind": "event",
                    "event_type": "time.point_entered",
                    "when": {
                        "op": "predicate",
                        "predicate": "time_point_is",
                        "args": {"value": "hour_18"},
                    },
                    "entry_branch_id": "default",
                },
                "execution": {
                    "branches": [{"id": "default", "entry_step_id": "schedule"}],
                    "steps": [
                        {
                            "id": "schedule",
                            "kind": "create_time_task",
                            "task": {
                                "task_key": "late_visitor",
                                "target": {"day_index": 0, "hour_of_day": 21},
                                "on_due_branch_id": "on_due",
                                "visibility": "hidden",
                            },
                            "next_step_id": "finish",
                        },
                        {"id": "finish", "kind": "finish"},
                    ],
                },
            }
        )
        on_due = RuleSpecV3.model_validate(
            {
                "id": "late_visitor_arrives",
                "priority": 50,
                "trigger": {
                    "kind": "event",
                    "event_type": "time.task_due",
                    "entry_branch_id": "never",
                },
                "execution": {
                    "branches": [
                        {"id": "never", "entry_step_id": "wrong"},
                        {"id": "on_due", "entry_step_id": "arrive"},
                    ],
                    "steps": [
                        {
                            "id": "arrive",
                            "kind": "effect",
                            "effect": {
                                "type": "change_entity_state",
                                "entity_id": "case_tracker",
                                "key": "visitor_arrived",
                                "value": True,
                            },
                            "next_step_id": "finish",
                        },
                        {
                            "id": "wrong",
                            "kind": "effect",
                            "effect": {
                                "type": "change_entity_state",
                                "entity_id": "case_tracker",
                                "key": "took_the_wrong_branch",
                                "value": True,
                            },
                            "next_step_id": "finish",
                        },
                        {"id": "finish", "kind": "finish"},
                    ],
                },
            }
        )
        return content.model_copy(
            update={"rules": (*content.rules, scheduler, on_due)}, deep=True
        )

    async def walk_to_the_task(self, engine, store):
        await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="wait-until-eight",
                    source_revision="0",
                    actor_id=ACTOR,
                    summary="等到晚上八点",
                    target=ActionTarget(kind="location", id="thomas_office"),
                    method=ActionMethod(family="rest", description="等待"),
                    check=NoAdjudicationCheck(),
                    success_effects=(
                        AdvanceWorldTimeEffect(to_point_id="hour_18"),
                        AdvanceWorldTimeEffect(to_point_id="hour_20"),
                    ),
                ),
            )
        )
        state = store.inspect_state(ROOM)
        occurrence_id = next(iter(state.time_occurrences))
        await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="wait-a-bit-longer",
                    source_revision=str(state.event_sequence),
                    actor_id=ACTOR,
                    summary="再等一会",
                    target=ActionTarget(kind="location", id="thomas_office"),
                    method=ActionMethod(family="rest", description="等待"),
                    check=NoAdjudicationCheck(),
                    success_effects=(AdvanceWorldTimeEffect(to_point_id=occurrence_id),),
                ),
            )
        )
        return occurrence_id

    def build(self):
        content = self.module_with_due_rule()
        store = InMemoryEngineStore()
        store.register_room(module_content=content, initial_state=game_state(content))
        return content, store, AdjudicationEngineService(store)

    async def test_entering_the_point_publishes_task_due_exactly_once(self) -> None:
        _, store, engine = self.build()

        await self.walk_to_the_task(engine, store)

        due = [
            event
            for event in store.inspect_domain_events(ROOM)
            if event.type == "time.task_due"
        ]
        self.assertEqual(len(due), 1)
        self.assertEqual(due[0].payload["task_key"], "late_visitor")

    async def test_the_task_is_completed_in_the_same_commit_as_its_event(self) -> None:
        """单次发布靠的是这个：重试从 completed 的状态重跑，没有第二条事件。"""

        _, store, engine = self.build()

        await self.walk_to_the_task(engine, store)

        state = store.inspect_state(ROOM)
        task = next(iter(state.time_tasks.values()))
        self.assertEqual(task.status, "completed")
        # 一次性临时点进入之后就不该再出现在后续排序里。
        self.assertEqual(state.time_occurrences, {})
        self.assertEqual(due_tasks(state, task.occurrence_id), ())

    async def test_settling_again_from_the_committed_state_emits_nothing(self) -> None:
        """恢复 / 重放走的就是这条路：状态已经是终态，结算是空操作。"""

        _, store, engine = self.build()
        await self.walk_to_the_task(engine, store)
        state = store.inspect_state(ROOM)

        again, due = settle_due_tasks(state, state.world_time)

        self.assertEqual(due, ())
        self.assertEqual(again.time_tasks, state.time_tasks)

    async def test_the_due_event_enters_the_branch_the_task_declared(self) -> None:
        """规则的入口分支是 `never`，任务声明的是 `on_due`。"""

        _, store, engine = self.build()

        await self.walk_to_the_task(engine, store)

        entities = store.inspect_state(ROOM).entities["case_tracker"]
        self.assertIs(entities.get("visitor_arrived"), True)
        self.assertNotIn("took_the_wrong_branch", entities)

    async def test_a_hidden_task_never_reaches_the_player(self) -> None:
        """隐藏任务的存在、来源与后果都不进玩家侧投影。"""

        content, store, engine = self.build()

        await self.walk_to_the_task(engine, store)

        due = next(
            event
            for event in store.inspect_domain_events(ROOM)
            if event.type == "time.task_due"
        )
        self.assertEqual(due.visibility, "hidden")

        state = store.inspect_state(ROOM)
        runtime = EngineRuntimeSnapshot(
            module_id=content.module_id,
            module_version=content.version,
            module_content=content,
            game_state=state,
            revision=str(state.event_sequence),
        )
        world = project_v3(runtime, player_id=PLAYER, actor_id=ACTOR).world

        # 玩家只看到按 canonical segment 解析出的安全 label，看不到 21:00、
        # 看不到任务来源，也看不到临时点的 id。
        self.assertEqual(world.time_label, "晚上")
        dumped = json.dumps(world.model_dump(), ensure_ascii=False)
        for leaked in ("21", "late_visitor", "occ_"):
            self.assertNotIn(leaked, dumped)


class DueOrderingTests(unittest.TestCase):
    def test_same_moment_tasks_settle_by_priority_then_id(self) -> None:
        """顺序稳定，断线恢复重放出来的世界才和第一次跑出来的一样。"""

        content = module()
        state = create_initial_game_state(content, room_id="room_01", actors={})
        for key, priority in (("late", 9), ("early", 1), ("middle", 5)):
            step = CreateTimeTaskStep(
                id="schedule",
                task=task_spec(
                    task_key=key,
                    target=TimeTaskTargetSpec(day_index=0, hour_of_day=15),
                    priority=priority,
                ),
                next_step_id="finish",
            )
            state, _, _ = create_time_task(content, state, step, rule_id="night_watch")

        at_fifteen = state.model_copy(
            update={
                "world_time": WorldTimeState(
                    current=WorldTimePoint(day_index=0, hour_of_day=15),
                    current_point_id="occ_d0_h15",
                    current_time_segment="afternoon",
                )
            },
            deep=True,
        )

        _, due = settle_due_tasks(at_fifteen, at_fifteen.world_time)

        self.assertEqual([task.priority for task in due], [1, 5, 9])


if __name__ == "__main__":
    unittest.main()
