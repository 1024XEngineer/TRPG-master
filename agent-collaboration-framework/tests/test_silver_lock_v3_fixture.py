"""验证《银之锁》不仅结构合法，而且能由真实 v3 引擎完成和恢复。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdjudicationExecution,
    CancelCheckChoice,
    ChangeEntityStateEffect,
    CheckDecisionRequest,
    ModuleContentV3,
    NoAdjudicationCheck,
    PlayerViewScope,
    PostRollDecisionRequest,
    RequiredAdjudicationCheck,
    RuleDecisionRef,
    SelectCheckChoice,
    SkillCheckCandidate,
    SubmitAdjudicationRequest,
)
from collaboration_framework.contracts.validation import (
    AdjudicationValidationError,
)
from collaboration_framework.engine import (
    ActorResources,
    ActorState,
    AdjudicationEngineService,
    DiceRoller,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
    SequenceDiceSource,
    audit_runtime_capabilities,
)
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.module import validate_module_v3

FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "银之锁"
)
FIXTURE = FIXTURE_DIR / "module-content-v3.json"
ROOM = "silver-lock-room"
PLAYER = "silver-lock-player"
ACTOR = "silver-lock-actor"


def load_module() -> ModuleContentV3:
    """读取本次发布的固定版本，测试不得回退到旧 v2 草稿。"""

    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def state(*, trusted: bool = False) -> GameState:
    """构造接近真实建卡结果的单人房间状态。"""

    content = load_module()
    seeded = create_initial_game_state(
        content,
        room_id=ROOM,
        actors={
            ACTOR: ActorState(
                player_id=PLAYER,
                name="测试调查员",
                source_character_id="silver-lock-character",
                source_character_version=1,
                state={
                    "skills": {"spot-hidden": 70, "listen": 60, "brawl": 65},
                    "attributes": {"STR": 60},
                },
                # 被动理智检定的目标值读这里；真实建卡由
                # `room.py::_character_runtime_resources` 从 derived_stats 填入。
                resources=ActorResources(san=60, luck=45),
            )
        },
    )
    entities = {entity_id: dict(values) for entity_id, values in seeded.entities.items()}
    # 主线测试跳过被动 SAN 的交互 UI；对应规则能力由独立断言覆盖。
    entities["rat_thing"]["san_resolved"] = True
    entities["door_monitor"]["san_resolved"] = True
    entities["bast"].update({"trusted": trusted, "following": trusted})
    return seeded.model_copy(update={"entities": entities}, deep=True)


class SilverLockContentGateTests(unittest.TestCase):
    """覆盖发布前必须全绿的静态质量门禁。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = load_module()

    def test_schema_semantics_and_runtime_capabilities_pass(self) -> None:
        report = validate_module_v3(self.content)
        self.assertEqual(report.status, "pass", report.errors)
        self.assertEqual(audit_runtime_capabilities(self.content), ())

    def test_all_travelable_locations_are_reachable(self) -> None:
        adjacency: dict[str, list[str]] = {}
        for edge in self.content.location_edges:
            adjacency.setdefault(edge.from_location_id, []).append(edge.to_location_id)
        reached = {self.content.initial_state.start_location_id}
        frontier = list(reached)
        while frontier:
            for neighbour in adjacency.get(frontier.pop(), []):
                if neighbour not in reached:
                    reached.add(neighbour)
                    frontier.append(neighbour)
        self.assertEqual(reached, {location.id for location in self.content.locations})

    def test_every_review_object_has_source_mapping(self) -> None:
        mapping = json.loads(
            (FIXTURE_DIR / "module-content-provenance.json").read_text(encoding="utf-8")
        )
        expected = {
            "locations": {item.id for item in self.content.locations},
            "information": {item.id for item in self.content.information},
            "rules": {item.id for item in self.content.rules},
            "knowledge_goals": {item.id for item in self.content.knowledge_goals},
            "ending_anchors": {item.id for item in self.content.ending_anchors},
        }
        for collection, ids in expected.items():
            self.assertEqual(set(mapping[collection]), ids, collection)
            self.assertTrue(all(mapping[collection][item_id] for item_id in ids))

    def test_sketchbook_has_only_three_fixed_products(self) -> None:
        fixed_rules = {
            rule.id for rule in self.content.rules if rule.id.startswith("materialize_")
        }
        self.assertEqual(
            fixed_rules,
            {
                "materialize_flashlight",
                "materialize_bolt_cutters",
                "materialize_osmanthus_porridge",
            },
        )
        serialized = FIXTURE.read_text(encoding="utf-8")
        self.assertNotIn("ensure_runtime_entity", serialized)
        self.assertNotIn("commit_terminal_ending", serialized)
        self.assertNotIn("inventory.has", serialized)

    def test_top_drawer_contains_sketchbook(self) -> None:
        entities = {entity.id: entity for entity in self.content.entities}
        self.assertIn(
            ("contains", "sketchbook"),
            {
                (relation.kind, relation.target_id)
                for relation in entities["top_drawer"].relations
            },
        )

    def test_sanity_and_fight_use_supported_check_steps(self) -> None:
        rules = {rule.id: rule for rule in self.content.rules}
        for rule_id in ("rat_thing_sanity", "door_ghost_sanity"):
            profiles = {
                step.check.profile_id
                for step in rules[rule_id].execution.steps
                if step.kind == "check"
            }
            self.assertEqual(profiles, {"coc7.sanity"})
        self.assertIn(
            "adjudicated_check",
            {step.kind for step in rules["fight_blinded_kidnapper"].execution.steps},
        )

    def test_specific_ending_precedes_generic_escape(self) -> None:
        self.assertEqual(self.content.ending_anchors[0].id, "kill_kidnapper_then_escape")
        self.assertEqual(self.content.ending_anchors[1].id, "escape_after_lock_breaks")


class SilverLockRuntimeTests(unittest.IsolatedAsyncioTestCase):
    """用真实规则服务与裁决服务执行主线和抓回恢复。"""

    def setUp(self) -> None:
        self.content = load_module()
        self.store = InMemoryEngineStore()
        self.store.register_room(module_content=self.content, initial_state=state())
        self.engine = AdjudicationEngineService(
            self.store,
            dice=DiceRoller(SequenceDiceSource([5] * 20)),
        )
        self.rules = RuleEngineService(self.store)
        self.sequence = 0

    async def revision(self) -> str:
        """每次提交前读取最新 revision，确保测试也服从 CAS。"""

        view = await self.rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        return view.revision

    async def choose(
        self,
        rule_id: str,
        option_id: str,
        family: str,
        target_kind: str,
        target_id: str,
        *,
        check_skill: str | None = None,
    ) -> AdjudicationExecution:
        """提交一个真实规则候选，并在需要时完成选骰和落骰确认。"""

        self.sequence += 1
        request_id = f"silver-lock-{self.sequence}"
        check = NoAdjudicationCheck()
        if check_skill is not None:
            check = RequiredAdjudicationCheck(
                candidates=(
                    SkillCheckCandidate(
                        candidate_id=option_id,
                        skill_id=check_skill,
                        difficulty="regular",
                        method_summary=f"使用 {check_skill}",
                        player_safe_reason="这是当前声明的行动方式",
                    ),
                )
            )
        execution = await self.engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id=request_id,
                    source_revision=await self.revision(),
                    actor_id=ACTOR,
                    summary=f"执行 {rule_id}",
                    target=ActionTarget(kind=target_kind, id=target_id),
                    method=ActionMethod(family=family, description=family),
                    rule_decision=RuleDecisionRef(rule_id=rule_id, option_id=option_id),
                    check=check,
                    success_effects=(),
                    failure_effects=(),
                ),
            )
        )
        if check_skill is None:
            return execution
        pending = execution.pending_decision
        self.assertIsNotNone(pending)
        assert pending is not None
        rolled = await self.engine.decide(
            CheckDecisionRequest(
                request_id=f"{request_id}:select",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=execution.view_revision,
                decision_id=pending.decision_id,
                decision_version=pending.decision_version,
                choice=SelectCheckChoice(candidate_id=option_id),
            )
        )
        self.assertIsNotNone(rolled.check_run)
        assert rolled.check_run is not None
        return await self.engine.decide_post_roll(
            PostRollDecisionRequest(
                request_id=f"{request_id}:accept",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=rolled.view_revision,
                check_id=rolled.check_run.check_id,
                check_version=rolled.check_run.version,
                option_id="accept-current",
            )
        )

    async def test_opening_top_drawer_reveals_sketchbook(self) -> None:
        before = await self.rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        initially_visible = {entity.id for entity in before.scene.visible_entities}
        self.assertNotIn("sketchbook", initially_visible)
        self.assertTrue(
            {"flashlight_page", "cutters_page", "porridge_page", "communication_page"}
            .isdisjoint(initially_visible)
        )

        await self.choose(
            "inspect_wall_painting",
            "lift-painting",
            "inspect",
            "entity",
            "wall_painting",
        )
        execution = await self.choose(
            "open_top_drawer",
            "wall-key",
            "open",
            "entity",
            "top_drawer",
        )

        discovered = tuple(
            evidence
            for evidence in execution.narration_evidence
            if evidence.subject_id == "sketchbook"
        )
        self.assertEqual(len(discovered), 1)
        self.assertTrue(discovered[0].required_in_narration)
        self.assertIn("四页速写本", discovered[0].subject_name)
        self.assertIn(
            ("top_drawer", "open", True),
            {
                (result.target_id, result.state_key, result.state_value)
                for result in execution.committed_results
            },
        )

        after = await self.rules.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        visible = {entity.id: entity for entity in after.scene.visible_entities}
        self.assertLessEqual(
            {
                "sketchbook",
                "flashlight_page",
                "cutters_page",
                "porridge_page",
                "communication_page",
            },
            set(visible),
        )
        self.assertIn("不能显现清单之外的物品", visible["sketchbook"].description)
        self.assertIn(
            "sketchbook_found",
            {information.id for information in after.known_information},
        )
        current = self.store.inspect_state(ROOM)
        self.assertIs(current.entities["top_drawer"]["open"], True)
        self.assertIs(current.entities["sketchbook"]["discovered"], True)

    async def prepare_bast_and_door(self, *, feed_bast: bool) -> None:
        """执行房间谜题，按参数决定芭斯特是否跟随。"""

        actions = [
            ("cut_restraints_with_knife", "pencil-knife", "cut", "entity", "restraint_rope", None),
            ("inspect_wall_painting", "lift-painting", "inspect", "entity", "wall_painting", None),
            ("open_top_drawer", "wall-key", "open", "entity", "top_drawer", None),
            ("materialize_flashlight", "fixed-flashlight", "tear", "entity", "flashlight_page", None),
            ("materialize_bolt_cutters", "fixed-cutters", "draw", "entity", "cutters_page", None),
            ("materialize_osmanthus_porridge", "fixed-porridge", "draw", "entity", "porridge_page", None),
            ("move_bed", "STR", "move", "entity", "bed", "STR"),
            ("open_middle_drawer", "bed-key", "open", "entity", "middle_drawer", None),
            ("light_vent", "flashlight", "illuminate", "entity", "vent", None),
            ("open_bottom_drawer", "vent-key", "open", "entity", "bottom_drawer", None),
            ("contact_bast_with_white_paper", "use-white-paper", "write", "entity", "white_paper", None),
            ("cut_wardrobe_chain", "bolt-cutters", "cut", "entity", "wardrobe", None),
        ]
        for action in actions:
            await self.choose(*action[:5], check_skill=action[5])
        if feed_bast:
            await self.choose(
                "feed_bast", "osmanthus-porridge", "feed", "entity", "bast"
            )
        await self.choose(
            "ask_bast_to_open_door", "bast-opens-door", "ask", "entity", "bast"
        )

    async def test_mainline_reaches_specific_ending_facts(self) -> None:
        await self.prepare_bast_and_door(feed_bast=True)
        await self.choose(
            "enter_corridor",
            "cross-silver-door",
            "enter",
            "entity",
            "silver_door",
        )
        current = self.store.inspect_state(ROOM)
        self.assertEqual(current.scene_id, "corridor")
        self.assertIs(current.entities["silver_lock"]["active"], False)
        self.assertIs(current.entities["bast"]["alive"], False)

        await self.choose(
            "fight_blinded_kidnapper",
            "fight-back",
            "fight",
            "entity",
            "kidnapper",
            check_skill="brawl",
        )
        await self.choose(
            "escape_through_exit", "escape", "escape", "location", "outside"
        )
        finished = self.store.inspect_state(ROOM)
        self.assertEqual(finished.scene_id, "outside")
        self.assertTrue(finished.core_resolved)
        self.assertTrue(finished.ending_available)
        self.assertLessEqual(
            {"silver_lock_broken", "kidnapper_defeated", "investigator_escaped"},
            set(finished.discovered_facts),
        )

    async def test_unprotected_attempt_returns_to_room_and_preserves_progress(self) -> None:
        await self.prepare_bast_and_door(feed_bast=False)
        await self.choose(
            "enter_corridor",
            "cross-silver-door",
            "enter",
            "entity",
            "silver_door",
        )
        returned = self.store.inspect_state(ROOM)
        self.assertEqual(returned.scene_id, "sealed_room")
        self.assertIs(returned.entities["silver_door"]["opened"], False)
        self.assertIs(returned.entities["silver_lock"]["boundary_triggered"], False)
        self.assertIs(returned.entities["sketchbook"]["discovered"], True)
        self.assertIs(returned.entities["bast"]["freed"], True)
        self.assertIn("captured_and_returned", returned.discovered_facts)


class SilverLockPassiveCheckTests(unittest.IsolatedAsyncioTestCase):
    """银之锁的两处被动理智检定必须真的弹出来（#398 §阶段三）。

    主线测试把 `san_resolved` 预置成 True 跳过了这两处——因为在 #398 之前它们
    根本走不通：`awaiting_passive_check` 在 `trpg-backend/app` 与
    `collaboration_framework/host` 下 grep 零命中，规则前面的 `mark` 效果照常
    提交，检定本身静默丢失。这里把 `san_resolved` 放回 False，钉住它们现在会
    经由既有检定工作流正常出现并结算。
    """

    def _room(self) -> tuple[InMemoryEngineStore, AdjudicationEngineService, GameState]:
        content = load_module()
        initial = state()
        entities = {key: dict(value) for key, value in initial.entities.items()}
        # 放回未结算：主线测试为了跳过 UI 交互才把它们设成 True。
        entities["rat_thing"].update({"seen": False, "san_resolved": False})
        entities["door_monitor"].update({"ghost_seen": False, "san_resolved": False})
        store = InMemoryEngineStore()
        store.register_room(
            module_content=content,
            initial_state=initial.model_copy(
                update={"entities": entities}, deep=True
            ),
        )
        return store, AdjudicationEngineService(store), initial

    async def _sight(
        self,
        engine: AdjudicationEngineService,
        *,
        request_id: str,
        entity_id: str,
        key: str,
    ):
        return await engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id=request_id,
                    source_revision="0",
                    actor_id=ACTOR,
                    summary="看清眼前的东西",
                    target=ActionTarget(kind="entity", id=entity_id),
                    method=ActionMethod(family="observe", description="定睛细看"),
                    check=NoAdjudicationCheck(),
                    success_effects=(
                        ChangeEntityStateEffect(
                            entity_id=entity_id, key=key, value=True
                        ),
                    ),
                ),
            )
        )

    async def test_rat_thing_sanity_reaches_the_player(self) -> None:
        store, engine, _ = self._room()

        execution = await self._sight(
            engine, request_id="see-rat", entity_id="rat_thing", key="seen"
        )

        self.assertEqual(execution.status, "awaiting_skill_choice")
        pending = execution.pending_decision
        assert pending is not None
        self.assertEqual(len(pending.options), 1)
        self.assertEqual(pending.options[0].display_name, "理智")
        self.assertEqual(pending.options[0].target_value, 60)
        self.assertFalse(pending.allow_cancel)
        # 检定之前的 `mark` 效果照常提交。
        self.assertIs(
            store.inspect_state(ROOM).entities["rat_thing"]["san_resolved"], True
        )
        # Agenda 还在途，游标停在检定步上。
        agenda = next(iter(store.inspect_state(ROOM).rule_agendas.values()))
        self.assertEqual(agenda.status, "awaiting_passive_check")
        self.assertEqual(agenda.current_rule_id, "rat_thing_sanity")
        self.assertEqual(agenda.current_step_id, "san")
        self.assertEqual(agenda.pending_check_id, pending.decision_id)

    async def test_door_ghost_sanity_reaches_the_player(self) -> None:
        store, engine, _ = self._room()

        execution = await self._sight(
            engine,
            request_id="see-ghost",
            entity_id="door_monitor",
            key="ghost_seen",
        )

        self.assertEqual(execution.status, "awaiting_skill_choice")
        pending = execution.pending_decision
        assert pending is not None
        self.assertEqual(pending.options[0].display_name, "理智")
        self.assertFalse(pending.allow_cancel)
        agenda = next(iter(store.inspect_state(ROOM).rule_agendas.values()))
        self.assertEqual(agenda.current_rule_id, "door_ghost_sanity")

    async def test_a_rule_forced_check_cannot_be_cancelled(self) -> None:
        """`CheckStep` 没有 `cancel_step_id`，取消它就是把 Agenda 永久卡住。"""

        _, engine, _ = self._room()
        execution = await self._sight(
            engine, request_id="see-rat", entity_id="rat_thing", key="seen"
        )
        pending = execution.pending_decision
        assert pending is not None

        with self.assertRaises(AdjudicationValidationError) as caught:
            await engine.decide(
                CheckDecisionRequest(
                    request_id="cancel-rat-san",
                    room_id=ROOM,
                    player_id=PLAYER,
                    source_revision=execution.view_revision,
                    decision_id=pending.decision_id,
                    decision_version=pending.decision_version,
                    choice=CancelCheckChoice(),
                )
            )
        self.assertEqual(caught.exception.result.code, "CHECK_NOT_CANCELLABLE")

    async def test_the_agenda_resumes_and_settles(self) -> None:
        store = InMemoryEngineStore()
        content = load_module()
        initial = state()
        entities = {key: dict(value) for key, value in initial.entities.items()}
        entities["rat_thing"].update({"seen": False, "san_resolved": False})
        store.register_room(
            module_content=content,
            initial_state=initial.model_copy(update={"entities": entities}, deep=True),
        )
        engine = AdjudicationEngineService(
            store, dice=DiceRoller(SequenceDiceSource([12]))
        )

        execution = await self._sight(
            engine, request_id="see-rat", entity_id="rat_thing", key="seen"
        )
        pending = execution.pending_decision
        assert pending is not None
        rolled = await engine.decide(
            CheckDecisionRequest(
                request_id="rat-san-roll",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=execution.view_revision,
                decision_id=pending.decision_id,
                decision_version=pending.decision_version,
                choice=SelectCheckChoice(candidate_id=pending.options[0].candidate_id),
            )
        )
        assert rolled.check_run is not None
        resolved = await engine.decide_post_roll(
            PostRollDecisionRequest(
                request_id="rat-san-accept",
                room_id=ROOM,
                player_id=PLAYER,
                source_revision=rolled.view_revision,
                check_id=rolled.check_run.check_id,
                check_version=rolled.check_run.version,
                option_id="accept-current",
            )
        )

        self.assertEqual(resolved.status, "resolved")
        # 六个 degree 全部路由到 finish，所以这里只验证「恢复到稳定」本身。
        # 让检定产生分叉属模组内容工作，扣 SAN 属 #401——都不在本 Issue 范围内。
        self.assertEqual(store.inspect_state(ROOM).rule_agendas, {})


if __name__ == "__main__":
    unittest.main()
