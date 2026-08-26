"""#415 的两条时间线验收标准，测在引擎输入层。

这两条以前测在纯函数层——直接调 `advanced_to_next`，绕过效果校验器、submit
路径、事件发布和投影。纯函数层证明不了「玩家提交一次推进会发生什么」，而那正是
验收标准的措辞。

差别不是形式上的：#437 的两条 P1（临时点进入后卡死、多人提案不合并临时点）都
是从这条缝里漏出去的——它们只在真实提交路径上跑第二跳时才暴露。
"""

from __future__ import annotations

import unittest

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdjudicationValidationError,
    AdvanceWorldTimeEffect,
    NoAdjudicationCheck,
    PlayerViewScope,
    SubmitAdjudicationRequest,
    TerminalTimePointSpec,
)
from collaboration_framework.engine import (
    ActorState,
    AdjudicationEngineService,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
)
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.engine.models import EngineRuntimeSnapshot
from collaboration_framework.engine.projection_v3 import keeper_capabilities_v3
from tests.time_fixtures import (
    DAY_NIGHT_POINTS,
    single_night_module,
    time_fixture_module,
)

ROOM = "time-acceptance-room"
PLAYER = "time-acceptance-player"
ACTOR = "time-acceptance-actor"


def opening_state(content) -> GameState:
    return create_initial_game_state(
        content,
        room_id=ROOM,
        actors={
            ACTOR: ActorState(
                player_id=PLAYER,
                name="调查员",
                source_character_id="character",
                source_character_version=1,
            )
        },
    )


class TimelineAcceptanceTests(unittest.IsolatedAsyncioTestCase):
    def build(self, content):
        store = InMemoryEngineStore()
        store.register_room(
            module_content=content, initial_state=opening_state(content)
        )
        return store, AdjudicationEngineService(store), RuleEngineService(store)

    async def advance(self, store, engine, *, to_point_id=None, tag="jump"):
        """走一次真实提交，而不是直接调时间线函数。"""

        revision = str(store.inspect_state(ROOM).event_sequence)
        return await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id=f"{tag}-{revision}",
                    source_revision=revision,
                    actor_id=ACTOR,
                    summary="等到下一个时间点",
                    target=ActionTarget(kind="location", id="only_room"),
                    method=ActionMethod(family="wait", description="等待"),
                    check=NoAdjudicationCheck(),
                    success_effects=(AdvanceWorldTimeEffect(to_point_id=to_point_id),),
                ),
            )
        )

    async def label_now(self, rules) -> str:
        view = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        return view.world.time_label

    def keeper_time(self, store, content):
        state = store.inspect_state(ROOM)
        runtime = EngineRuntimeSnapshot(
            module_id=content.module_id,
            module_version=content.version,
            module_content=content,
            game_state=state,
            revision=str(state.event_sequence),
        )
        return keeper_capabilities_v3(runtime, actor_id=ACTOR).time

    async def test_a_single_night_module_walks_five_points_across_midnight(
        self,
    ) -> None:
        """验收：单夜模组依次经过 5 个点，day_index 在午夜正确递增。"""

        content = single_night_module()
        store, engine, rules = self.build(content)

        seen = [
            (
                store.inspect_state(ROOM).world_time.current_point_id,
                store.inspect_state(ROOM).world_time.current.day_index,
            )
        ]
        labels = [await self.label_now(rules)]
        for _ in range(4):
            await self.advance(store, engine)
            world = store.inspect_state(ROOM).world_time
            seen.append((world.current_point_id, world.current.day_index))
            labels.append(await self.label_now(rules))

        self.assertEqual(
            seen,
            [
                ("hour_18", 0),
                ("hour_20", 0),
                ("hour_22", 0),
                ("hour_00", 1),  # 越过 22 点回卷，day_index 递增
                ("hour_02", 1),
            ],
        )
        # 玩家依次看到 晚上 / 晚上 / 深夜 / 凌晨 / 凌晨：22 点走模组逐点声明的
        # label，其余走 canonical segment 的缺省推导。
        self.assertEqual(labels, ["晚上", "晚上", "深夜", "凌晨", "凌晨"])

    async def test_every_jump_publishes_the_point_it_actually_entered(self) -> None:
        content = single_night_module()
        store, engine, _ = self.build(content)

        for _ in range(4):
            await self.advance(store, engine)

        entered = [
            event.payload["point_id"]
            for event in store.inspect_domain_events(ROOM)
            if event.type == "time.point_entered"
        ]
        self.assertEqual(entered, ["hour_20", "hour_22", "hour_00", "hour_02"])

    async def test_the_terminal_point_refuses_the_next_submit(self) -> None:
        """验收：到达终点后推进被拒，结构化理由 code 为 terminal_point_reached。"""

        content = single_night_module()
        store, engine, _ = self.build(content)
        for _ in range(4):
            await self.advance(store, engine)

        before = store.inspect_state(ROOM).world_time

        with self.assertRaises(AdjudicationValidationError) as raised:
            await self.advance(store, engine, tag="past-the-end")

        self.assertEqual(raised.exception.result.code, "TIME_ADVANCE_BLOCKED")
        self.assertIn(
            "terminal_point_reached", raised.exception.result.internal_reason or ""
        )

        # 拒绝必须是原子的：世界时间一点没动。
        after = store.inspect_state(ROOM).world_time
        self.assertEqual(after.current_point_id, before.current_point_id)
        self.assertEqual(after.current.day_index, before.current.day_index)

    async def test_the_terminal_point_stops_time_without_ending_the_game(self) -> None:
        """终点只停时间：phase 不变，玩家仍可行动。"""

        content = single_night_module()
        store, engine, rules = self.build(content)
        for _ in range(4):
            await self.advance(store, engine)

        state = store.inspect_state(ROOM)
        self.assertEqual(state.phase, "playing")
        self.assertFalse(state.core_resolved)
        self.assertIsNone(state.ending_id)

        view = await rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertFalse(view.world.can_advance_time)

    async def test_keeper_loses_the_next_point_at_the_terminal(self) -> None:
        content = single_night_module()
        store, engine, _ = self.build(content)

        opening = self.keeper_time(store, content)
        assert opening is not None
        self.assertEqual(opening.next_point_id, "hour_20")
        self.assertIsNone(opening.blocked_reason)

        for _ in range(4):
            await self.advance(store, engine)

        ended = self.keeper_time(store, content)
        assert ended is not None
        self.assertIsNone(ended.next_point_id)
        assert ended.blocked_reason is not None
        self.assertEqual(ended.blocked_reason.code, "terminal_point_reached")
        # 精确时刻在 Keeper 侧照常保留。
        self.assertEqual((ended.current_day_index, ended.current_hour_of_day), (1, 2))

    async def test_a_multi_day_module_stops_only_on_the_declared_occurrence(
        self,
    ) -> None:
        """验收：第三天 18:00 为终点，前两次进入 hour_18 仍可继续。"""

        content = time_fixture_module(
            points=DAY_NIGHT_POINTS,
            start_point_id="hour_06",
            terminal_point=TerminalTimePointSpec(point_id="hour_18", day_index=2),
        )
        store, engine, _ = self.build(content)

        seen = []
        for _ in range(5):  # 06→18 D0, 06 D1, 18 D1, 06 D2, 18 D2
            await self.advance(store, engine)
            world = store.inspect_state(ROOM).world_time
            seen.append((world.current_point_id, world.current.day_index))

        self.assertEqual(
            seen,
            [
                ("hour_18", 0),  # 第一次进入 hour_18，可以继续
                ("hour_06", 1),
                ("hour_18", 1),  # 第二次进入，仍可继续
                ("hour_06", 2),
                ("hour_18", 2),  # 第三次进入，到此为止
            ],
        )

        with self.assertRaises(AdjudicationValidationError) as raised:
            await self.advance(store, engine, tag="fourth-evening")
        self.assertEqual(raised.exception.result.code, "TIME_ADVANCE_BLOCKED")

    async def test_a_day_night_module_hits_each_segment_once_per_day(self) -> None:
        """只有昼夜之分的模组不会因为默认四点而让同一条 night 规则每天命中两次。"""

        content = time_fixture_module(points=DAY_NIGHT_POINTS, start_point_id="hour_06")
        store, engine, _ = self.build(content)

        segments = []
        for _ in range(4):
            await self.advance(store, engine)
            segments.append(store.inspect_state(ROOM).world_time.time_segment)

        self.assertEqual(segments, ["evening", "morning", "evening", "morning"])


if __name__ == "__main__":
    unittest.main()
