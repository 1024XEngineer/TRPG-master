"""验证《幸福蛙蛙村》固定 V3 内容能由真实引擎走通关键分支。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
    AdjudicationExecution,
    AdvanceWorldTimeEffect,
    CheckDecisionRequest,
    EnterLocationEffect,
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
from collaboration_framework.engine import (
    ActorState,
    AdjudicationEngineService,
    DiceRoller,
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
    / "幸福蛙蛙村"
)
FIXTURE = FIXTURE_DIR / "module-content-v3.json"
ROOM = "happy-frog-room"
PLAYER = "happy-frog-player"
ACTOR = "happy-frog-actor"


def load_module() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def initial_state():
    """构造覆盖模组所有固定检定技能的单人调查员。"""

    skills = dict.fromkeys(
        (
            "library-use",
            "persuade",
            "psychoanalysis",
            "psychology",
            "spot-hidden",
            "natural-world",
            "stealth",
            "swim",
        ),
        80,
    )
    return create_initial_game_state(
        load_module(),
        room_id=ROOM,
        actors={
            ACTOR: ActorState(
                player_id=PLAYER,
                name="测试调查员",
                source_character_id="happy-frog-character",
                source_character_version=1,
                state={"skills": skills, "attributes": {"POW": 80}},
            )
        },
    )


class HappyFrogContentGateTests(unittest.TestCase):
    """覆盖第三个预设发布前的静态门禁。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = load_module()

    def test_schema_semantics_and_runtime_capabilities_pass(self) -> None:
        report = validate_module_v3(self.content)
        self.assertEqual(report.status, "pass", report.errors)
        self.assertEqual(audit_runtime_capabilities(self.content), ())

    def test_agent_rules_have_explicit_candidate_boundaries(self) -> None:
        for rule in self.content.rules:
            if rule.trigger.kind != "agent_match":
                continue
            scope = rule.trigger.scope
            self.assertTrue(scope.action_families, rule.id)
            self.assertTrue(scope.location_ids, rule.id)
            self.assertTrue(scope.target_kinds, rule.id)
            self.assertTrue(scope.target_ids, rule.id)
            self.assertTrue(rule.trigger.options, rule.id)

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

    def test_terminal_actions_are_behind_engine_enforced_routes(self) -> None:
        edges = {edge.id: edge for edge in self.content.location_edges}
        rules = {rule.id: rule for rule in self.content.rules}
        locations = {location.id: location for location in self.content.locations}
        self.assertTrue(edges["pond_to_crystal_shore"].conditions)
        self.assertIn("boundary_to_outside_back", edges)
        self.assertEqual(
            edges["boundary_to_outside_back"].to_location_id,
            "resort_boundary",
        )
        self.assertTrue(edges["guest_to_staff"].conditions)
        self.assertNotIn("final_confrontation", locations)
        self.assertIn("两层别墅", locations["frog_resort"].player_visible_description)
        self.assertIn("别墅", locations["resort_reception"].aliases)
        hierarchy_only = {"resort_villa", "resort_ground_floor", "resort_second_floor"}
        self.assertTrue(all(locations[item].kind == "region" for item in hierarchy_only))
        self.assertFalse(
            hierarchy_only
            & {
                endpoint
                for edge in self.content.location_edges
                for endpoint in (edge.from_location_id, edge.to_location_id)
            }
        )
        self.assertEqual(edges["resort_to_reception"].to_location_id, "resort_reception")
        self.assertEqual(edges["reception_stairs_to_guest"].to_location_id, "guest_room")
        self.assertEqual(edges["reception_to_staff"].from_location_id, "resort_reception")
        self.assertTrue(edges["reception_to_staff"].conditions)
        self.assertEqual(locations["resort_reception"].parent_location_id, "resort_ground_floor")
        self.assertEqual(locations["guest_room"].parent_location_id, "resort_second_floor")
        self.assertEqual(locations["staff_area"].parent_location_id, "resort_second_floor")
        self.assertEqual(
            rules["destroy_dream_crystal"].trigger.scope.location_ids,
            ("crystal_shore",),
        )
        self.assertEqual(
            rules["persuade_happiness_messenger"].trigger.scope.location_ids,
            ("resort_reception",),
        )


class HappyFrogRuntimeTests(unittest.IsolatedAsyncioTestCase):
    """通过真实规则服务和裁决服务回放结局、失败重试与时间事件。"""

    def setUp(self) -> None:
        self.content = load_module()
        self.store = InMemoryEngineStore()
        self.store.register_room(
            module_content=self.content,
            initial_state=initial_state(),
        )
        self.engine = AdjudicationEngineService(
            self.store,
            dice=DiceRoller(SequenceDiceSource([5] * 40)),
        )
        self.rules = RuleEngineService(self.store)
        self.sequence = 0

    async def revision(self) -> str:
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
        self.sequence += 1
        request_id = f"happy-frog-rule-{self.sequence}"
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

    async def move(self, location_id: str) -> None:
        self.sequence += 1
        await self.engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id=f"happy-frog-travel-{self.sequence}",
                    source_revision=await self.revision(),
                    actor_id=ACTOR,
                    summary=f"前往 {location_id}",
                    target=ActionTarget(kind="location", id=location_id),
                    method=ActionMethod(family="travel", description="沿已知路线移动"),
                    persistence_intent="location",
                    check=NoAdjudicationCheck(),
                    success_effects=(EnterLocationEffect(location_id=location_id),),
                ),
            )
        )

    async def advance(self, point_id: str) -> None:
        self.sequence += 1
        await self.engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id=f"happy-frog-time-{self.sequence}",
                    source_revision=await self.revision(),
                    actor_id=ACTOR,
                    summary=f"推进至 {point_id}",
                    target=ActionTarget(kind="world", id=self.content.world_ref),
                    method=ActionMethod(family="wait", description="等待时间推进"),
                    check=NoAdjudicationCheck(),
                    success_effects=(AdvanceWorldTimeEffect(to_point_id=point_id),),
                ),
            )
        )

    async def reach_reception(self) -> None:
        for location_id in (
            "pretrip_investigation",
            "forest_road",
            "resort_reception",
        ):
            await self.move(location_id)

    async def test_evidence_path_persuades_messenger_and_rescues_james(self) -> None:
        await self.reach_reception()
        self.assertIs(self.store.inspect_state(ROOM).entities["final_debate"]["available"], False)
        capabilities = await self.rules.read_keeper_capabilities(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertNotIn(
            "persuade_happiness_messenger",
            {candidate.rule_id for candidate in capabilities.rule_candidates},
        )
        await self.choose(
            "read_messenger_intent",
            "psychology",
            "analyze",
            "entity",
            "messenger",
            check_skill="psychology",
        )
        await self.move("frog_pond")
        await self.choose(
            "study_dream_frogs",
            "natural-world",
            "study",
            "entity",
            "dream_frogs",
            check_skill="natural-world",
        )
        await self.move("resort_reception")
        self.assertIs(self.store.inspect_state(ROOM).entities["final_debate"]["available"], True)
        await self.choose(
            "persuade_happiness_messenger",
            "persuade-with-evidence",
            "persuade",
            "entity",
            "final_debate",
            check_skill="persuade",
        )

        finished = self.store.inspect_state(ROOM)
        self.assertTrue(finished.core_resolved)
        self.assertTrue(finished.ending_available)
        self.assertLessEqual(
            {"messenger_convinced", "victims_released", "james_returns_home"},
            set(finished.discovered_facts),
        )
        self.assertIs(finished.entities["messenger"]["convinced"], True)
        self.assertIs(finished.entities["james"]["released"], True)

    async def test_retrieved_crystal_path_breaks_core(self) -> None:
        await self.reach_reception()
        await self.choose(
            "infiltrate_staff_area",
            "stealth",
            "sneak",
            "entity",
            "staff_door",
            check_skill="stealth",
        )
        await self.move("messenger_bedroom")
        await self.choose(
            "read_messenger_notes",
            "library-use",
            "research",
            "entity",
            "messenger_notes",
            check_skill="library-use",
        )
        await self.move("staff_area")
        await self.move("resort_reception")
        await self.move("frog_pond")
        await self.move("crystal_shore")
        blocked = self.store.inspect_state(ROOM)
        self.assertEqual(blocked.scene_id, "frog_pond")
        capabilities = await self.rules.read_keeper_capabilities(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertNotIn(
            "destroy_dream_crystal",
            {candidate.rule_id for candidate in capabilities.rule_candidates},
        )
        await self.choose(
            "retrieve_dream_crystal",
            "swim",
            "retrieve",
            "entity",
            "dream_crystal",
            check_skill="swim",
        )
        await self.move("crystal_shore")
        await self.choose(
            "destroy_dream_crystal",
            "break-crystal",
            "destroy",
            "entity",
            "dream_crystal",
        )

        finished = self.store.inspect_state(ROOM)
        self.assertTrue(finished.core_resolved)
        self.assertTrue(finished.ending_available)
        self.assertLessEqual(
            {"crystal_destroyed", "victims_released", "james_returns_home"},
            set(finished.discovered_facts),
        )
        self.assertIs(finished.entities["dream_crystal"]["destroyed"], True)

    async def test_early_leave_is_an_explicit_supported_ending(self) -> None:
        await self.reach_reception()
        await self.move("resort_boundary")
        await self.choose(
            "leave_frog_resort",
            "leave-now",
            "leave",
            "location",
            "outside",
        )
        finished = self.store.inspect_state(ROOM)
        self.assertEqual(finished.scene_id, "outside")
        self.assertTrue(finished.core_resolved)
        self.assertTrue(finished.ending_available)
        self.assertIn("escaped_unresolved", finished.discovered_facts)
        await self.move("resort_boundary")
        self.assertEqual(self.store.inspect_state(ROOM).scene_id, "resort_boundary")

    async def test_forcing_unreleased_james_out_commits_tragic_ending(self) -> None:
        await self.reach_reception()
        await self.choose(
            "force_james_against_his_will",
            "force-james",
            "restrain",
            "entity",
            "james",
        )
        resisting = self.store.inspect_state(ROOM)
        self.assertIs(resisting.entities["james"]["forced_removal"], True)
        self.assertIs(resisting.entities["james"]["alive"], True)
        self.assertIn("james_resists_forced_removal", resisting.discovered_facts)

        await self.choose(
            "force_james_out_of_resort",
            "force-james-outside",
            "carry",
            "location",
            "outside",
        )
        finished = self.store.inspect_state(ROOM)
        self.assertEqual(finished.scene_id, "outside")
        self.assertTrue(finished.core_resolved)
        self.assertTrue(finished.ending_available)
        self.assertIs(finished.entities["james"]["released"], False)
        self.assertIs(finished.entities["james"]["alive"], False)
        self.assertIn("james_forced_removal_tragedy", finished.discovered_facts)
        self.assertNotIn("james_returns_home", finished.discovered_facts)
        self.assertNotIn("escaped_unresolved", finished.discovered_facts)

    async def test_failed_clue_check_can_be_retried_without_dead_end(self) -> None:
        self.engine = AdjudicationEngineService(
            self.store,
            dice=DiceRoller(SequenceDiceSource([99, 5])),
        )
        await self.move("pretrip_investigation")
        await self.choose(
            "research_missing_people",
            "library-use",
            "research",
            "entity",
            "missing_files",
            check_skill="library-use",
        )
        after_failure = self.store.inspect_state(ROOM)
        self.assertIn("missing_people_pattern", after_failure.discovered_facts)

        await self.choose(
            "research_missing_people",
            "library-use",
            "research",
            "entity",
            "missing_files",
            check_skill="library-use",
        )
        after_retry = self.store.inspect_state(ROOM)
        self.assertIn("resort_has_no_registration", after_retry.discovered_facts)

    async def test_night_ritual_activates_on_real_timeline_events(self) -> None:
        await self.advance("hour_18")
        await self.advance("hour_22")
        current = self.store.inspect_state(ROOM)
        self.assertEqual(current.world_time.current_point_id, "hour_22")
        self.assertIs(current.entities["night_ritual"]["active"], True)
        self.assertIn("night_has_fallen", current.discovered_facts)
        entered = [
            event.payload["point_id"]
            for event in self.store.inspect_domain_events(ROOM)
            if event.type == "time.point_entered"
        ]
        self.assertEqual(entered, ["hour_18", "hour_22"])

    async def test_multiplayer_start_publishes_only_local_rule_candidates(self) -> None:
        actors = {
            actor_id: ActorState(
                player_id=player_id,
                name=name,
                source_character_id=f"character-{actor_id}",
                source_character_version=1,
            )
            for actor_id, player_id, name in (
                ("actor-a", "player-a", "甲调查员"),
                ("actor-b", "player-b", "乙调查员"),
            )
        }
        state = create_initial_game_state(
            self.content,
            room_id="happy-frog-multiplayer-room",
            actors=actors,
        )
        store = InMemoryEngineStore()
        store.register_room(module_content=self.content, initial_state=state)
        rules = RuleEngineService(store)

        for actor_id, player_id in (("actor-a", "player-a"), ("actor-b", "player-b")):
            capabilities = await rules.read_keeper_capabilities(
                PlayerViewScope(
                    room_id="happy-frog-multiplayer-room",
                    player_id=player_id,
                    actor_id=actor_id,
                )
            )
            published = {candidate.rule_id for candidate in capabilities.rule_candidates}
            self.assertEqual(
                published,
                {"accept_lane_commission", "inspect_resort_flyer"},
            )
            self.assertNotIn("destroy_dream_crystal", published)
            self.assertNotIn("persuade_happiness_messenger", published)


if __name__ == "__main__":
    unittest.main()
