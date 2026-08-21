"""事件屏障：规则按**事件发生时**的状态匹配（#398 §阶段二）。

`AdvanceWorldTimeEffect` 的文档字符串一直这样写着：

> Sleeping from noon until 20:00 is therefore two of these in sequence, and
> each one publishes its own `time.point_entered`, so a Rule that watches for
> nightfall still fires on the point it was written against instead of being
> skipped over.

效果本身确实照做了——每一跳都发自己的事件。但结算发生在**全部**效果跑完之后，
`matching_event_rules` 拿到的 `state` 已经是终态。于是 18:00 的
`time.point_entered` 用 06:00 的世界去判 `time_of_day_is night`，规则照样被跳过，
只是原因从「事件没发出来」换成了「快照拿错了」。

这就是《追书人》「睡到第二天早晨」：玩家一次提交四个时间推进，夜间监视点永远
开不出来，叙事只能写成「安稳睡到早晨」。
"""

from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdvanceWorldTimeEffect,
    ChangeEntityStateEffect,
    ModuleContentV3,
    NoAdjudicationCheck,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    ActorResources,
    ActorState,
    AdjudicationEngineService,
    GameState,
    InMemoryEngineStore,
)
from collaboration_framework.engine.models import WorldTimePoint, WorldTimeState

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)
ROOM = "barrier-room"
PLAYER = "barrier-player"
ACTOR = "barrier-actor"

# 《追书人》的时间线：00 / 06 / 12 / 18 / 20，夜间是 18:00–06:00。
# 中午躺下、睡到第二天早晨要跨过 18 → 20 → 00 → 06 四个点，其中前三个是夜里。
SLEEP_UNTIL_MORNING = ("hour_18", "hour_20", "hour_00", "hour_06")


def module() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def noon_state() -> GameState:
    return GameState(
        room_id=ROOM,
        scene_id="thomas_office",
        actors={
            ACTOR: ActorState(
                player_id=PLAYER,
                name="调查员",
                source_character_id="character",
                source_character_version=1,
                resources=ActorResources(san=55, luck=50),
            )
        },
        entities={"case_tracker": {"surveillance_available": False}},
        world_time=WorldTimeState(
            current_point_id="hour_12",
            current=WorldTimePoint(day_index=0, hour_of_day=12),
        ),
    )


class EventBarrierTests(unittest.IsolatedAsyncioTestCase):
    async def test_night_rule_fires_on_the_point_it_was_written_against(self) -> None:
        store = InMemoryEngineStore()
        store.register_room(module_content=module(), initial_state=noon_state())
        engine = AdjudicationEngineService(store)

        execution = await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="sleep-until-morning",
                    source_revision="0",
                    actor_id=ACTOR,
                    summary="睡到第二天早晨",
                    target=ActionTarget(kind="location", id="thomas_office"),
                    method=ActionMethod(family="rest", description="和衣睡下"),
                    check=NoAdjudicationCheck(),
                    success_effects=tuple(
                        AdvanceWorldTimeEffect(to_point_id=point)
                        for point in SLEEP_UNTIL_MORNING
                    ),
                ),
            )
        )

        self.assertEqual(execution.status, "resolved")
        state = store.inspect_state(ROOM)
        # 四跳都跑完了，世界确实到了第二天早晨。
        self.assertEqual(state.world_time.current_point_id, "hour_06")
        self.assertEqual(state.world_time.current.day_index, 1)
        # 而 18:00 那一跳按**当时**的世界匹配，夜间监视点开了出来。
        # 修好之前这里是 False：终态是 06:00，`time_of_day_is night` 判否。
        self.assertIs(state.entities["case_tracker"]["surveillance_available"], True)

    async def test_the_rule_fires_once_even_across_three_night_points(self) -> None:
        """18 / 20 / 00 三个点都是夜里，但规则的条件自己会关掉它。

        屏障不负责去重——`surveillance_available == false` 这个前置条件负责。
        钉住它是为了确认屏障没有把「每个事件都重新匹配一遍」变成「同一条规则
        被跑了三次」。
        """

        store = InMemoryEngineStore()
        store.register_room(module_content=module(), initial_state=noon_state())
        engine = AdjudicationEngineService(store)

        await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="sleep-until-morning",
                    source_revision="0",
                    actor_id=ACTOR,
                    summary="睡到第二天早晨",
                    target=ActionTarget(kind="location", id="thomas_office"),
                    method=ActionMethod(family="rest", description="和衣睡下"),
                    check=NoAdjudicationCheck(),
                    success_effects=tuple(
                        AdvanceWorldTimeEffect(to_point_id=point)
                        for point in SLEEP_UNTIL_MORNING
                    ),
                ),
            )
        )

        events = store.inspect_domain_events(ROOM)
        triggered = [
            event
            for event in events
            if event.type == "rule.triggered"
            and event.payload["rule_id"] == "enable_night_surveillance"
        ]
        self.assertEqual(len(triggered), 1)
        # 触发它的是 18:00 那条事件，不是最后那条。
        source_id = triggered[0].payload["source_event_id"]
        source = next(event for event in events if event.event_id == source_id)
        self.assertEqual(source.type, "time.point_entered")
        self.assertEqual(source.payload["point_id"], "hour_18")

    async def test_an_unblocked_action_still_runs_every_effect(self) -> None:
        """零回归：没有规则挡路时，效果序列的结果与屏障之前完全一致。"""

        store = InMemoryEngineStore()
        store.register_room(module_content=module(), initial_state=noon_state())
        engine = AdjudicationEngineService(store)

        execution = await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="tidy-notes",
                    source_revision="0",
                    actor_id=ACTOR,
                    summary="整理笔记",
                    target=ActionTarget(kind="entity", id="case_tracker"),
                    method=ActionMethod(family="research", description="逐条抄录"),
                    check=NoAdjudicationCheck(),
                    success_effects=(
                        ChangeEntityStateEffect(
                            entity_id="case_tracker",
                            key="notes_tidy",
                            value=True,
                        ),
                        ChangeEntityStateEffect(
                            entity_id="case_tracker",
                            key="notes_indexed",
                            value=True,
                        ),
                    ),
                ),
            )
        )

        self.assertEqual(execution.status, "resolved")
        tracker = store.inspect_state(ROOM).entities["case_tracker"]
        self.assertIs(tracker["notes_tidy"], True)
        self.assertIs(tracker["notes_indexed"], True)
        self.assertEqual(store.inspect_state(ROOM).rule_agendas, {})


if __name__ == "__main__":
    unittest.main()
