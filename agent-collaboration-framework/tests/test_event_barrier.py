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

import json
import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdvanceWorldTimeEffect,
    ChangeEntityStateEffect,
    ModuleContentV3,
    CheckDecisionRequest,
    NoAdjudicationCheck,
    PostRollDecisionRequest,
    SelectCheckChoice,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    ActorResources,
    ActorState,
    AdjudicationEngineService,
    GameState,
    InMemoryEngineStore,
)
from collaboration_framework.engine.dice import DiceRoller, SequenceDiceSource
from collaboration_framework.engine.models import WorldTimePoint, WorldTimeState
from tests.time_fixtures import NIGHT_LATCH_RULE, day_cycle_module

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

# 时间线 fixture 的点：00 / 06 / 12 / 18 / 20，夜间是 18:00–06:00。
# 中午躺下、睡到第二天早晨要跨过 18 → 20 → 00 → 06 四个点，其中前三个是夜里。
#
# 屏障要问的那个问题需要「连跨三个夜点、终态却是白天」这个形状。它此前是借
# 《追书人》的 time_policy 与 `enable_night_surveillance` 规则问出来的，于是这组
# 引擎测试被模组内容绑住——#451 把模组收敛成昼夜两点、并重写了那条规则之后就一起
# 断掉。形状与规则现在由 `tests/time_fixtures.py` 自己拥有。
SLEEP_UNTIL_MORNING = ("hour_18", "hour_20", "hour_00", "hour_06")


def module() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def barrier_module() -> ModuleContentV3:
    """带一条夜间闩规则的时间线 fixture，供屏障用例使用。"""

    return day_cycle_module(rules=(NIGHT_LATCH_RULE,))


def noon_state() -> GameState:
    return GameState(
        room_id=ROOM,
        scene_id="only_room",
        actors={
            ACTOR: ActorState(
                player_id=PLAYER,
                name="调查员",
                source_character_id="character",
                source_character_version=1,
                resources=ActorResources(san=55, luck=50),
            )
        },
        entities={"case_tracker": {"night_seen": False}},
        world_time=WorldTimeState(
            current_point_id="hour_12",
            current=WorldTimePoint(day_index=0, hour_of_day=12),
        ),
    )


class EventBarrierTests(unittest.IsolatedAsyncioTestCase):
    async def test_night_rule_fires_on_the_point_it_was_written_against(self) -> None:
        store = InMemoryEngineStore()
        store.register_room(module_content=barrier_module(), initial_state=noon_state())
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
                    target=ActionTarget(kind="location", id="only_room"),
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
        self.assertIs(state.entities["case_tracker"]["night_seen"], True)

    async def test_the_rule_fires_once_even_across_three_night_points(self) -> None:
        """18 / 20 / 00 三个点都是夜里，但规则的条件自己会关掉它。

        屏障不负责去重——`surveillance_available == false` 这个前置条件负责。
        钉住它是为了确认屏障没有把「每个事件都重新匹配一遍」变成「同一条规则
        被跑了三次」。
        """

        store = InMemoryEngineStore()
        store.register_room(module_content=barrier_module(), initial_state=noon_state())
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
                    target=ActionTarget(kind="location", id="only_room"),
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
            and event.payload["rule_id"] == "night_latch"
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
        store.register_room(module_content=barrier_module(), initial_state=noon_state())
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


def two_rules_state() -> GameState:
    """一条 `entity.state_changed` 同时点着两条规则的局面。

    `ghoul_crowd_sanity`（priority 180）要 `ghoul_crowd.revealed` 为真、
    `case_tracker.crowd_sight_resolved` 为假；`first_sight_of_douglas`（120）要
    `cemetery_figure.true_form_seen` 为真、`first_ghoul_sight_resolved` 为假。
    两者的条件互不相干，所以任何一条 `entity.state_changed` 都会同时命中。

    这正是 #398 失败案例 B 点名的两条规则。
    """

    return GameState(
        room_id=ROOM,
        scene_id="cemetery",
        actors={
            ACTOR: ActorState(
                player_id=PLAYER,
                name="调查员",
                source_character_id="character",
                source_character_version=1,
                resources=ActorResources(san=55, luck=50),
            )
        },
        entities={
            "ghoul_crowd": {"revealed": True},
            "cemetery_figure": {"true_form_seen": True},
            "case_tracker": {
                "crowd_sight_resolved": False,
                "first_ghoul_sight_resolved": False,
            },
            "favorite_grave": {"examined": False},
        },
        world_time=WorldTimeState(
            current_point_id="hour_18",
            current=WorldTimePoint(day_index=0, hour_of_day=18),
        ),
    )


def examine_grave(request_id: str, source_revision: str) -> SubmitAdjudicationRequest:
    """一个最普通的动作，只发一条 `entity.state_changed`。"""

    return SubmitAdjudicationRequest(
        room_id=ROOM,
        player_id=PLAYER,
        adjudication=ActionAdjudication(
            request_id=request_id,
            source_revision=source_revision,
            actor_id=ACTOR,
            summary="细看那座常去的坟",
            target=ActionTarget(kind="entity", id="favorite_grave"),
            method=ActionMethod(family="observe", description="俯身细看"),
            check=NoAdjudicationCheck(),
            success_effects=(
                ChangeEntityStateEffect(
                    entity_id="favorite_grave", key="examined", value=True
                ),
            ),
        ),
    )


class QueuedRuleDrainTests(unittest.IsolatedAsyncioTestCase):
    """一个事件点着多条规则时，第一条挂起不能把其余的吃掉（#398 失败案例 B）。

    `_enqueue_matching` 一次把匹配到的规则全部入队，而在此之前跑它们的 `for`
    循环一挂起就 `break`——队列里剩下的项没有任何读者，`finish()` 甚至会把带着
    `queued` 项的 Agenda 标成 `stable`。于是「同时看见食尸鬼群和道格拉斯真容」
    只会掷一次骰，第二条规则连同它的效果一起消失。
    """

    async def _resolve_pending_check(self, engine, execution, tag: str):
        pending = execution.pending_decision
        assert pending is not None
        rolled = await engine.decide(
            CheckDecisionRequest(
                request_id=f"{tag}-choose",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=execution.view_revision,
                decision_id=pending.decision_id,
                decision_version=pending.decision_version,
                choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
            )
        )
        assert rolled.check_run is not None
        return await engine.decide_post_roll(
            PostRollDecisionRequest(
                request_id=f"{tag}-accept",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=rolled.view_revision,
                check_id=rolled.check_run.check_id,
                check_version=rolled.check_run.version,
                option_id="accept-current",
            )
        )

    async def test_the_second_rule_on_one_event_still_fires_after_the_first_suspends(
        self,
    ) -> None:
        store = InMemoryEngineStore()
        store.register_room(module_content=module(), initial_state=two_rules_state())
        engine = AdjudicationEngineService(store)

        first = await engine.submit(examine_grave("grave-1", "0"))

        # 优先级高的先跑：食尸鬼群的理智检定先弹出来。
        self.assertEqual(first.status, "awaiting_skill_choice")
        self.assertIs(store.inspect_state(ROOM).entities["case_tracker"]["crowd_sight_resolved"], True)
        # 而道格拉斯那条还排在队列里，尚未触发。
        self.assertIs(
            store.inspect_state(ROOM).entities["case_tracker"]["first_ghoul_sight_resolved"],
            False,
        )

        second = await self._resolve_pending_check(engine, first, "crowd")

        # 修好之前：这里是 resolved，Agenda 标成 stable 而队列里那条永远没跑。
        self.assertEqual(second.status, "awaiting_skill_choice")
        assert second.pending_decision is not None
        self.assertEqual(second.pending_decision.options[0].display_name, "理智")
        self.assertFalse(second.pending_decision.allow_cancel)
        self.assertIs(
            store.inspect_state(ROOM).entities["case_tracker"]["first_ghoul_sight_resolved"],
            True,
        )
        # 两次检定挂在同一个 action_request_id 上——这正是迁移 b8c9d0e1f2a3 存在的理由。
        self.assertEqual(second.action_request_id, first.action_request_id)

        final = await self._resolve_pending_check(engine, second, "douglas")

        self.assertEqual(final.status, "resolved")
        state = store.inspect_state(ROOM)
        self.assertIs(state.entities["favorite_grave"]["examined"], True)
        # 两条规则都跑完了，游标不留痕。
        self.assertEqual(state.rule_agendas, {})

    async def test_a_suspended_agenda_carries_its_queue_across_the_request(self) -> None:
        """挂起时队列真的落库了，而不是靠同一次请求的内存活着。"""

        store = InMemoryEngineStore()
        store.register_room(module_content=module(), initial_state=two_rules_state())
        engine = AdjudicationEngineService(store)

        await engine.submit(examine_grave("grave-1", "0"))

        agendas = store.inspect_state(ROOM).rule_agendas
        self.assertEqual(len(agendas), 1)
        agenda = next(iter(agendas.values()))
        self.assertEqual(agenda.status, "awaiting_passive_check")
        queued = [item.rule_id for item in agenda.queue if item.status == "queued"]
        self.assertEqual(queued, ["first_sight_of_douglas"])


def failing_chain_module() -> ModuleContentV3:
    """《追书人》，但 `ghoul_crowd_sanity` 的 SAN 检定换成没有执行器的 step。

    改优先级最高的那条（180），它先跑，于是 `first_sight_of_douglas`（120）会
    停在 `queued` 上——正好同时钉住「链失败后剩余效果照跑」和「被跳过的规则
    进审计」两件事。

    用一条**能到达**的 event 规则，而不是造一个合成模组：模组自带的
    `invoke_ruleset_action` 只出现在 `temporary_insanity_leads_to_asylum` 里，
    而没有任何效果会发出 `actor.temporary_insanity`。
    """

    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    rule = next(item for item in data["rules"] if item["id"] == "ghoul_crowd_sanity")
    steps = rule["execution"]["steps"]
    next(step for step in steps if step["id"] == "mark_crowd")["next_step_id"] = (
        "no_executor"
    )
    rule["execution"]["steps"] = [
        step for step in steps if step["id"] != "crowd_san"
    ] + [
        {
            "id": "no_executor",
            "kind": "invoke_ruleset_action",
            "action_id": "coc7.apply_condition",
            "actor_binding": "actor",
            "parameters": {"condition": "unconscious"},
            "next_step_id": "finish",
        }
    ]
    return ModuleContentV3.model_validate(data)


def three_effect_action(request_id: str, source_revision: str) -> SubmitAdjudicationRequest:
    """三个效果的动作。第一个就会唤醒规则，后两个要等屏障放行。"""

    return SubmitAdjudicationRequest(
        room_id=ROOM,
        player_id=PLAYER,
        adjudication=ActionAdjudication(
            request_id=request_id,
            source_revision=source_revision,
            actor_id=ACTOR,
            summary="细看那座常去的坟，再翻开土层",
            target=ActionTarget(kind="entity", id="favorite_grave"),
            method=ActionMethod(family="observe", description="俯身细看"),
            check=NoAdjudicationCheck(),
            success_effects=(
                ChangeEntityStateEffect(
                    entity_id="favorite_grave", key="examined", value=True
                ),
                ChangeEntityStateEffect(
                    entity_id="favorite_grave", key="disturbed", value=True
                ),
                ChangeEntityStateEffect(
                    entity_id="favorite_grave", key="soil_loose", value=True
                ),
            ),
        ),
    )


class FailedChainDoesNotVetoTheActionTests(unittest.IsolatedAsyncioTestCase):
    """规则链失败不能把玩家的动作吃掉一半（#398 零回归）。

    `_drive_continuation` 此前只有 `if result.status == "suspended"` 一个收尾
    分支，而 `SettlementResult.status` 还能是 `failed`。落到 failed 时父动作剩下
    的效果被静默丢弃、`action.succeeded` 不发，可 execution 照样报
    `outcome="success"`——ActionPlan 于是踩着一个只做了一半的世界继续往下走。

    屏障管的是结算时机，不是否决权：#398 明确要求「新增执行屏障不得改变无阻塞
    动作的既有结果」，而屏障之前这三个效果本来就会全部执行。
    """

    async def test_remaining_effects_still_run_when_the_rule_chain_fails(self) -> None:
        store = InMemoryEngineStore()
        store.register_room(
            module_content=failing_chain_module(),
            initial_state=two_rules_state(),
        )
        engine = AdjudicationEngineService(store)

        execution = await engine.submit(three_effect_action("grave-1", "0"))

        # 规则链确实断了，而且说得出断在哪。
        self.assertEqual(execution.status, "rule_failed")
        self.assertEqual(execution.rule_failure_code, "step_kind_has_no_executor")
        # 动作本身照常完成——两件事分别由 outcome 与 status 承担。
        self.assertEqual(execution.outcome, "success")

        grave = store.inspect_state(ROOM).entities["favorite_grave"]
        # 修好之前：后两个效果凭空消失，而 execution 仍报 success。
        self.assertIs(grave["examined"], True)
        self.assertIs(grave["disturbed"], True)
        self.assertIs(grave["soil_loose"], True)

        events = store.inspect_domain_events(ROOM)
        self.assertIn("action.succeeded", {event.type for event in events})
        failure = next(event for event in events if event.type == "rule.agenda_failed")
        # 这两个效果没再参与规则结算，审计里说清楚有几个。
        self.assertEqual(failure.payload["unsettled_effect_count"], 2)
        # 排在失败那条后面的规则同样没跑过。
        self.assertEqual(failure.payload["skipped_rule_ids"], ["first_sight_of_douglas"])
        self.assertEqual(store.inspect_state(ROOM).rule_agendas, {})


class UnsupportedBoundaryTests(unittest.IsolatedAsyncioTestCase):
    """事件规则挂在没人推进的边界上时显式失败（#398 §目标 5）。"""

    async def test_an_active_check_inside_an_event_rule_fails_instead_of_hanging(
        self,
    ) -> None:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        rule = next(
            item for item in data["rules"] if item["id"] == "ghoul_crowd_sanity"
        )
        step = next(
            item for item in rule["execution"]["steps"] if item["id"] == "crowd_san"
        )
        step["check"]["initiation_kind"] = "active_action"

        store = InMemoryEngineStore()
        store.register_room(
            module_content=ModuleContentV3.model_validate(data),
            initial_state=two_rules_state(),
        )
        engine = AdjudicationEngineService(store)

        execution = await engine.submit(three_effect_action("grave-1", "0"))

        # 修好之前：resolved / success，外加一个永远不会动的 Agenda 留在库里。
        self.assertEqual(execution.status, "rule_failed")
        self.assertEqual(
            execution.rule_failure_code,
            "rule_boundary_unsupported:awaiting_active_check",
        )
        self.assertEqual(store.inspect_state(ROOM).rule_agendas, {})
        # 父动作照样跑完。
        self.assertIs(
            store.inspect_state(ROOM).entities["favorite_grave"]["soil_loose"], True
        )


class RuleOwnedCheckAuthorityTests(unittest.IsolatedAsyncioTestCase):
    """规则拥有的检定，菜单与掷骰对象都由规则的 spec 说了算（#398 §阶段三）。"""

    @staticmethod
    def _module_with_passive_check(**check_overrides) -> ModuleContentV3:
        data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        rule = next(
            item for item in data["rules"] if item["id"] == "ghoul_crowd_sanity"
        )
        step = next(
            item for item in rule["execution"]["steps"] if item["id"] == "crowd_san"
        )
        step["check"].update(check_overrides)
        return ModuleContentV3.model_validate(data)

    async def _roll_and_read_options(self, module_content):
        store = InMemoryEngineStore()
        store.register_room(
            module_content=module_content,
            initial_state=two_rules_state(),
        )
        # 目标值 55，掷 90 必失败——奖惩骰菜单才有内容可看。
        engine = AdjudicationEngineService(
            store, dice=DiceRoller(SequenceDiceSource([90]))
        )
        execution = await engine.submit(examine_grave("grave-1", "0"))
        pending = execution.pending_decision
        assert pending is not None
        rolled = await engine.decide(
            CheckDecisionRequest(
                request_id="crowd-choose",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=execution.view_revision,
                decision_id=pending.decision_id,
                decision_version=pending.decision_version,
                choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
            )
        )
        assert rolled.check_run is not None
        self.assertFalse(rolled.check_run.roll.passed)
        return {option.option_id for option in rolled.check_run.post_roll_options}

    async def test_a_rule_can_forbid_pushing_its_own_check(self) -> None:
        """`allow_push` / `allow_luck` 此前零消费者——规则说不出「这次不许 push」。"""

        allowed = await self._roll_and_read_options(self._module_with_passive_check())
        # 默认（两个字段为 null）行为不变：四处线上被动检定都走这一条。
        self.assertIn("push-once", allowed)

        forbidden = await self._roll_and_read_options(
            self._module_with_passive_check(allow_push=False, allow_luck=False)
        )
        self.assertNotIn("push-once", forbidden)
        self.assertFalse({item for item in forbidden if item.startswith("spend-luck")})
        self.assertEqual(forbidden, {"accept-current"})

    async def test_an_unsupported_actor_binding_fails_instead_of_rolling_for_the_actor(
        self,
    ) -> None:
        """引擎只会替行动者掷骰；替错人掷比不掷更糟。

        `actor_binding` 是登记过的值空间（`ACTOR_BINDINGS` 有四个取值），发布期
        照收，但运行时 `_passive_check_option` 一直无条件用 `adjudication.actor_id`。
        解析绑定是新能力（#347 §4.8 排除），所以这里只要求它别静默走错。
        """

        store = InMemoryEngineStore()
        store.register_room(
            module_content=self._module_with_passive_check(actor_binding="target"),
            initial_state=two_rules_state(),
        )
        engine = AdjudicationEngineService(store)

        execution = await engine.submit(examine_grave("grave-1", "0"))

        self.assertEqual(execution.status, "rule_failed")
        self.assertEqual(
            execution.rule_failure_code, "rule_check_actor_binding_unsupported"
        )
        self.assertEqual(store.inspect_state(ROOM).rule_agendas, {})
