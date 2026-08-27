"""Durable RuleAgenda ordering, suspension, and lease recovery (#226 §4)."""

from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    ChangeEntityStateEffect,
    ModuleContentV3,
    NoAdjudicationCheck,
    SubmitAdjudicationRequest,
)
from collaboration_framework.engine import (
    ActorResources,
    ActorState,
    AdjudicationEngineService,
    AgendaItem,
    AgendaSource,
    GameState,
    InMemoryEngineStore,
    RevisionConflictError,
    RuleAgenda,
)
from collaboration_framework.engine.rules_v3 import (
    ordered_agenda_items,
    resume_agenda_rule,
)

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)
ROOM = "agenda-room"
PLAYER = "agenda-player"
ACTOR = "agenda-actor"


def module() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def game_state(**updates) -> GameState:
    values = {
        "room_id": ROOM,
        "scene_id": "cemetery",
        "actors": {
            ACTOR: ActorState(
                player_id=PLAYER,
                name="调查员",
                source_character_id="character",
                source_character_version=1,
                # 被动理智检定的目标值读 `resources.san`；真实建卡由
                # `room.py::_character_runtime_resources` 从 derived_stats 填入。
                resources=ActorResources(san=55, luck=50),
            )
        },
        "entities": {
            "cemetery_figure": {"true_form_seen": False},
            "case_tracker": {"first_ghoul_sight_resolved": False},
        },
    }
    values.update(updates)
    return GameState(**values)


def agenda(agenda_id: str, event_sequence: int, priority: int) -> RuleAgenda:
    return RuleAgenda(
        agenda_id=agenda_id,
        room_id=ROOM,
        module_id="paper-chase",
        module_version="3.0.0",
        correlation_id=f"correlation-{agenda_id}",
        root_source=AgendaSource(kind="event", id=f"event-{agenda_id}"),
        revision="4",
        current_rule_id=f"rule-{agenda_id}",
        current_branch_id="default",
        current_step_id="invoke",
        queue=(
            AgendaItem(
                source_event_id=f"event-{agenda_id}",
                event_sequence=event_sequence,
                rule_id=f"rule-{agenda_id}",
                rule_priority=priority,
                branch_id="default",
                status="running",
            ),
        ),
    )


class RuleAgendaOrderingTests(unittest.TestCase):
    def test_items_sort_by_event_then_priority_then_rule_id(self) -> None:
        items = (
            AgendaItem(
                source_event_id="event-2",
                event_sequence=2,
                rule_id="rule-a",
                rule_priority=900,
                branch_id="default",
            ),
            AgendaItem(
                source_event_id="event-1",
                event_sequence=1,
                rule_id="rule-z",
                rule_priority=20,
                branch_id="default",
            ),
            AgendaItem(
                source_event_id="event-1",
                event_sequence=1,
                rule_id="rule-b",
                rule_priority=80,
                branch_id="default",
            ),
            AgendaItem(
                source_event_id="event-1",
                event_sequence=1,
                rule_id="rule-a",
                rule_priority=80,
                branch_id="default",
            ),
        )
        ordered = ordered_agenda_items(items)
        self.assertEqual(
            [item.rule_id for item in ordered],
            ["rule-a", "rule-b", "rule-z", "rule-a"],
        )


class RuleAgendaRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_event_check_suspends_with_effect_and_cursor_in_same_state(
        self,
    ) -> None:
        content = module()
        store = InMemoryEngineStore()
        store.register_room(module_content=content, initial_state=game_state())
        engine = AdjudicationEngineService(store)

        await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="see-ghoul",
                    source_revision="0",
                    actor_id=ACTOR,
                    summary="看清墓地里的人影",
                    target=ActionTarget(kind="entity", id="cemetery_figure"),
                    method=ActionMethod(family="observe", description="仔细观察"),
                    check=NoAdjudicationCheck(),
                    success_effects=(
                        ChangeEntityStateEffect(
                            entity_id="cemetery_figure",
                            key="true_form_seen",
                            value=True,
                        ),
                    ),
                ),
            )
        )

        state = store.inspect_state(ROOM)
        self.assertTrue(state.entities["case_tracker"]["first_ghoul_sight_resolved"])
        self.assertEqual(len(state.rule_agendas), 1)
        persisted = next(iter(state.rule_agendas.values()))
        self.assertEqual(persisted.status, "awaiting_passive_check")
        self.assertEqual(persisted.current_rule_id, "first_sight_of_douglas")
        self.assertEqual(persisted.current_step_id, "san_check")
        self.assertGreater(persisted.step_count, 0)
        resumed_rule, resumed_walk = resume_agenda_rule(persisted, content)
        self.assertEqual(resumed_rule.id, "first_sight_of_douglas")
        self.assertEqual(resumed_walk.suspended_at, "san_check")

    async def test_expired_lease_is_reclaimed_without_replaying_agenda(self) -> None:
        first = agenda("first", event_sequence=1, priority=20)
        second = agenda("second", event_sequence=2, priority=900)
        store = InMemoryEngineStore()
        store.register_room(
            module_content=module(),
            initial_state=game_state(
                rule_agendas={first.agenda_id: first, second.agenda_id: second}
            ),
        )
        now = datetime(2026, 8, 10, tzinfo=UTC)
        claimed = await store.claim_rule_agenda(
            room_id=ROOM,
            worker_id="worker-a",
            now=now,
            lease_expires_at=now + timedelta(seconds=5),
        )
        assert claimed is not None
        self.assertEqual(claimed.agenda_id, "first")

        other = await store.claim_rule_agenda(
            room_id=ROOM,
            worker_id="worker-b",
            now=now,
            lease_expires_at=now + timedelta(seconds=20),
        )
        assert other is not None
        self.assertEqual(other.agenda_id, "second")

        recovered = await store.claim_rule_agenda(
            room_id=ROOM,
            worker_id="worker-c",
            now=now + timedelta(seconds=6),
            lease_expires_at=now + timedelta(seconds=30),
        )
        assert recovered is not None
        self.assertEqual(recovered.agenda_id, "first")
        self.assertGreater(recovered.lease_version, claimed.lease_version)
        with self.assertRaises(RevisionConflictError):
            await store.checkpoint_rule_agenda(
                agenda=claimed,
                worker_id="worker-a",
                expected_lease_version=claimed.lease_version,
                now=now + timedelta(seconds=6),
            )

        completed = recovered.model_copy(update={"status": "stable"})
        saved = await store.checkpoint_rule_agenda(
            agenda=completed,
            worker_id="worker-c",
            expected_lease_version=recovered.lease_version,
            now=now + timedelta(seconds=7),
        )
        self.assertEqual(saved.status, "stable")
        self.assertIsNone(saved.lease_owner)


def module_dict() -> dict:
    import json

    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def module_with_unexecutable_step() -> ModuleContentV3:
    """《追书人》，但 `locked_study_window_breaks` 撞上一个没有执行器的 step。

    模组自带的 `invoke_ruleset_action` 只出现在 `temporary_insanity_leads_to_asylum`
    里，而没有任何效果会发出 `actor.temporary_insanity`——它在当前内容里到不了。
    这里把一条**能到达**的 event 规则改成停在同一种 step 上，用来验收「无执行器
    的 step kind 显式失败」这条，而不是造一个与真实模组无关的合成模组。
    """

    data = module_dict()
    rule = next(
        item for item in data["rules"] if item["id"] == "locked_study_window_breaks"
    )
    steps = rule["execution"]["steps"]
    next(step for step in steps if step["id"] == "break_window")["next_step_id"] = (
        "apply_condition"
    )
    steps.append(
        {
            "id": "apply_condition",
            "kind": "invoke_ruleset_action",
            "action_id": "coc7.unknown_action",
            "actor_binding": "actor",
            "parameters": {"condition": "unconscious"},
            "next_step_id": "finish",
        }
    )
    return ModuleContentV3.model_validate(data)


def window_state(**updates) -> GameState:
    """开局：调查员还没看到墓地探访，书房窗户锁着且完好。

    随后把 `case_tracker.books_taken` 翻成 true 就会触发
    `locked_study_window_breaks`——这是《追书人》里唯一一条不掷骰、跑完就 stable
    的 event 规则。#451 之后它挂在「他确实进屋取到了书」上，而不是「你看见了他」：
    看见与翻窗发生在不同时刻，挂在前者会让人影同时出现在监视点和书房。
    """

    values = {
        "entities": {
            "cemetery_figure": {"visit_observed": False, "true_form_seen": False},
            "study_window": {"locked": True, "broken": False},
            "case_tracker": {"first_ghoul_sight_resolved": False, "books_taken": False},
        }
    }
    values.update(updates)
    return game_state(**values)


def observe_visit(request_id: str, source_revision: str) -> SubmitAdjudicationRequest:
    return SubmitAdjudicationRequest(
        room_id=ROOM,
        player_id=PLAYER,
        adjudication=ActionAdjudication(
            request_id=request_id,
            source_revision=source_revision,
            actor_id=ACTOR,
            summary="确认他这一夜取走了书",
            target=ActionTarget(kind="entity", id="case_tracker"),
            method=ActionMethod(family="observe", description="清点少掉的书"),
            check=NoAdjudicationCheck(),
            success_effects=(
                ChangeEntityStateEffect(
                    entity_id="case_tracker",
                    key="books_taken",
                    value=True,
                ),
            ),
        ),
    )


def repair_window(request_id: str, source_revision: str) -> SubmitAdjudicationRequest:
    return SubmitAdjudicationRequest(
        room_id=ROOM,
        player_id=PLAYER,
        adjudication=ActionAdjudication(
            request_id=request_id,
            source_revision=source_revision,
            actor_id=ACTOR,
            summary="把书房的窗户修好",
            target=ActionTarget(kind="entity", id="study_window"),
            method=ActionMethod(family="manipulate", description="重新装好窗格"),
            check=NoAdjudicationCheck(),
            success_effects=(
                ChangeEntityStateEffect(
                    entity_id="study_window",
                    key="broken",
                    value=False,
                ),
            ),
        ),
    )


class AgendaHygieneTests(unittest.IsolatedAsyncioTestCase):
    """`rule_agendas` 只装在途游标（#398 §阶段一）。

    在此之前它无条件落库，而全仓库没有任何删除路径（`del agendas` / `.pop` 均
    零命中）。于是每个触发规则的动作都会往一份每回合要全量 deepcopy + 校验的
    state 里永久追加一条死数据。
    """

    async def test_a_rule_that_runs_to_completion_leaves_nothing_behind(self) -> None:
        store = InMemoryEngineStore()
        store.register_room(module_content=module(), initial_state=window_state())
        engine = AdjudicationEngineService(store)

        execution = await engine.submit(observe_visit("observe-1", "0"))

        state = store.inspect_state(ROOM)
        # 规则确实跑了：窗户被撞开了。
        self.assertTrue(state.entities["study_window"]["broken"])
        self.assertEqual(execution.status, "resolved")
        self.assertIsNone(execution.rule_failure_code)
        # ……但它跑完就 stable，没有任何读者，所以不落库。
        self.assertEqual(state.rule_agendas, {})

    async def test_agenda_count_does_not_grow_with_actions(self) -> None:
        """同一个房间连跑多回合，条目数不随动作数增长——这是本条的整个要害。"""

        store = InMemoryEngineStore()
        store.register_room(
            module_content=module(),
            initial_state=window_state(
                entities={
                    "cemetery_figure": {
                        "visit_observed": True,
                        "true_form_seen": False,
                    },
                    "study_window": {"locked": True, "broken": True},
                    "case_tracker": {
                        "first_ghoul_sight_resolved": False,
                        "books_taken": True,
                    },
                }
            ),
        )
        engine = AdjudicationEngineService(store)

        for index in range(5):
            revision = str(store.inspect_state(ROOM).event_sequence)
            # 把窗户修好；规则立刻又把它撞开，于是每一回合都真的触发一次规则。
            await engine.submit(repair_window(f"repair-{index}", revision))
            self.assertEqual(store.inspect_state(ROOM).rule_agendas, {})
            self.assertTrue(store.inspect_state(ROOM).entities["study_window"]["broken"])

    async def test_agenda_count_does_not_grow_when_the_rule_chain_fails(self) -> None:
        """失败的规则链同样不留痕——上一条测的是跑到 stable 的规则。

        `test_agenda_count_does_not_grow_with_actions` 里那条规则每次都跑完，所以
        `rule_agendas == {}` 几乎是白给的：真正会积压的是**停下来**的 Agenda。这里
        让同一条规则每回合都撞死在没有执行器的 step 上，断言条目数照样不增长，
        而且每一次都留下一条可审计的失败。
        """

        store = InMemoryEngineStore()
        store.register_room(
            module_content=module_with_unexecutable_step(),
            initial_state=window_state(
                entities={
                    "cemetery_figure": {
                        "visit_observed": True,
                        "true_form_seen": False,
                    },
                    "study_window": {"locked": True, "broken": True},
                    "case_tracker": {
                        "first_ghoul_sight_resolved": False,
                        "books_taken": True,
                    },
                }
            ),
        )
        engine = AdjudicationEngineService(store)

        for index in range(5):
            revision = str(store.inspect_state(ROOM).event_sequence)
            execution = await engine.submit(repair_window(f"repair-{index}", revision))
            self.assertEqual(execution.status, "rule_failed")
            self.assertEqual(store.inspect_state(ROOM).rule_agendas, {})
            failures = [
                event
                for event in store.inspect_domain_events(ROOM)
                if event.type == "rule.agenda_failed"
            ]
            self.assertEqual(len(failures), index + 1)

    async def test_pre_existing_settled_agendas_are_pruned(self) -> None:
        """存量房间里已经积下的死数据随正常回合被扫掉，不需要单独的数据迁移。"""

        dead_stable = agenda("dead-stable", event_sequence=1, priority=10).model_copy(
            update={"status": "stable"}
        )
        dead_failed = agenda("dead-failed", event_sequence=2, priority=10).model_copy(
            update={"status": "failed", "failure_code": "agenda_budget_exceeded"}
        )
        store = InMemoryEngineStore()
        store.register_room(
            module_content=module(),
            initial_state=window_state(
                rule_agendas={
                    dead_stable.agenda_id: dead_stable,
                    dead_failed.agenda_id: dead_failed,
                }
            ),
        )
        engine = AdjudicationEngineService(store)

        await engine.submit(observe_visit("observe-1", "0"))

        self.assertEqual(store.inspect_state(ROOM).rule_agendas, {})

    async def test_an_in_flight_agenda_is_still_persisted(self) -> None:
        """卫生不是「不落库」，是「只落在途的」——挂在被动检定上的必须留下。"""

        store = InMemoryEngineStore()
        store.register_room(module_content=module(), initial_state=game_state())
        engine = AdjudicationEngineService(store)

        await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id="see-ghoul",
                    source_revision="0",
                    actor_id=ACTOR,
                    summary="看清墓地里的人影",
                    target=ActionTarget(kind="entity", id="cemetery_figure"),
                    method=ActionMethod(family="observe", description="仔细观察"),
                    check=NoAdjudicationCheck(),
                    success_effects=(
                        ChangeEntityStateEffect(
                            entity_id="cemetery_figure",
                            key="true_form_seen",
                            value=True,
                        ),
                    ),
                ),
            )
        )

        agendas = store.inspect_state(ROOM).rule_agendas
        self.assertEqual(len(agendas), 1)
        self.assertEqual(
            next(iter(agendas.values())).status, "awaiting_passive_check"
        )


class AgendaFailureAuditTests(unittest.IsolatedAsyncioTestCase):
    """撞上没有执行器的 step 时显式失败并留痕（#398 §阶段一）。"""

    async def test_step_without_executor_fails_loudly(self) -> None:
        store = InMemoryEngineStore()
        store.register_room(
            module_content=module_with_unexecutable_step(),
            initial_state=window_state(),
        )
        engine = AdjudicationEngineService(store)

        execution = await engine.submit(observe_visit("observe-1", "0"))

        # 此前：execution 报 resolved，Agenda 停在 running 上，无人推进也无信号。
        self.assertEqual(execution.status, "rule_failed")
        self.assertEqual(execution.rule_failure_code, "RULESET_ACTION_NOT_REGISTERED")
        # 动作本身成功了——是它触发的规则链没跑完，两件事分开记。
        self.assertEqual(execution.outcome, "success")

        state = store.inspect_state(ROOM)
        # 失败的 Agenda 同样是终态，一样不落库。
        self.assertEqual(state.rule_agendas, {})

        events = store.inspect_domain_events(ROOM)
        failures = [event for event in events if event.type == "rule.agenda_failed"]
        self.assertEqual(len(failures), 1)
        failure = failures[0]
        self.assertEqual(failure.visibility, "hidden")
        self.assertEqual(
            failure.payload["failure_code"], "RULESET_ACTION_NOT_REGISTERED"
        )
        self.assertEqual(failure.payload["rule_id"], "locked_study_window_breaks")
        self.assertEqual(failure.payload["step_id"], "apply_condition")
        # 失败的 Agenda 不落库，被跳过的规则只能靠 payload 留痕。
        self.assertEqual(failure.payload["skipped_rule_ids"], [])
        self.assertIn(failure.event_id, execution.event_refs)
        # 审计信号从不是规则的输入。
        self.assertNotIn(failure.event_id, execution.public_event_refs)
