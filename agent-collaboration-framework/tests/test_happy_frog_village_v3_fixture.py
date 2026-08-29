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
    PlayerInput,
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
from collaboration_framework.host.application import (
    ActionPlanNarrator,
    PlayerViewProjector,
)
from collaboration_framework.host.schemas import (
    ActionPlanNarrationContext,
    CompletedPlanStepSummary,
)
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


class _StaticNarrationModel:
    def __init__(self, text: str, evidence_refs: tuple[str, ...]) -> None:
        self.text = text
        self.evidence_refs = evidence_refs

    async def generate(self, context):
        return {
            "kind": "narration",
            "text": self.text,
            "claimed_evidence_refs": self.evidence_refs,
            "suggested_actions": [],
        }


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
    def test_all_npcs_have_stable_doubao_voice_profiles(self) -> None:
        """幸福蛙蛙村的 7 个 NPC 均配置同一资源包下的专属音色。"""

        content = load_module()
        profiles = {
            entity.id: entity.voice
            for entity in content.entities
            if entity.kind == "npc"
        }
        expected_ids = {
            "villager_accounts",
            "ezra",
            "messenger",
            "emily",
            "james",
            "frog_head_guest",
            "dream_frogs",
        }
        self.assertEqual(set(profiles), expected_ids)
        self.assertTrue(all(profile is not None for profile in profiles.values()))
        self.assertEqual({profile.provider for profile in profiles.values() if profile}, {"doubao"})
        self.assertEqual(
            {profile.resource_id for profile in profiles.values() if profile},
            {"seed-tts-2.0"},
        )

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

    def test_hard_crystal_retrieval_rejects_regular_success(self) -> None:
        rule = next(
            item for item in self.content.rules if item.id == "retrieve_dream_crystal"
        )
        check = next(item for item in rule.execution.steps if item.id == "check")
        self.assertEqual(check.check.difficulty, "hard")
        self.assertEqual(check.result_routes["hard_success"], "success_0")
        self.assertEqual(check.result_routes["regular_success"], "failure_0")

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
        await self.choose(
            "force_james_against_his_will",
            "force-james",
            "restrain",
            "entity",
            "james",
        )
        await self.choose(
            "carry_james_against_his_will",
            "carry-james",
            "carry",
            "entity",
            "james",
        )
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
        self.assertIs(finished.entities["james"]["under_forced_custody"], False)
        self.assertIs(finished.entities["james"]["accompanying_party"], False)
        await self.move("outside")
        self.assertIs(self.store.inspect_state(ROOM).entities["james"]["alive"], True)

    async def test_retrieved_crystal_path_breaks_core(self) -> None:
        await self.reach_reception()
        await self.choose(
            "force_james_against_his_will",
            "force-james",
            "restrain",
            "entity",
            "james",
        )
        await self.choose(
            "carry_james_against_his_will",
            "carry-james",
            "carry",
            "entity",
            "james",
        )
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
        retrieved = self.store.inspect_state(ROOM)
        self.assertEqual(retrieved.scene_id, "crystal_shore")
        self.assertIs(retrieved.entities["dream_crystal"]["retrieved"], True)
        self.assertEqual(
            retrieved.entities["dream_crystal"]["location_id"],
            "crystal_shore",
        )
        execution = await self.choose(
            "destroy_dream_crystal",
            "break-crystal",
            "destroy",
            "entity",
            "dream_crystal",
        )

        broken_result = next(
            result
            for result in execution.committed_results
            if result.target_id == "dream_crystal"
        )
        self.assertEqual(broken_result.kind, "object_state")
        self.assertEqual(broken_result.state_key, "broken")
        self.assertIs(broken_result.state_value, True)

        player_input = PlayerInput(
            room_id=ROOM,
            player_id=PLAYER,
            actor_id=ACTOR,
            client_action_id="narrate-broken-dream-crystal",
            utterance="把水晶狠狠砸碎，去除度假村的力量",
        )
        player_view = await PlayerViewProjector(self.rules).project(player_input)
        narration = await ActionPlanNarrator(
            _StaticNarrationModel(
                "水晶碎裂后，覆盖度假村的微光与雾气开始消散。",
                (broken_result.event_ref,),
            )
        ).narrate(
            ActionPlanNarrationContext(
                background=player_view.background,
                player_input=player_input,
                plan_goal=player_input.utterance,
                termination_status="resolved",
                completed_steps=(
                    CompletedPlanStepSummary(
                        step_index=0,
                        semantic_goal=player_input.utterance,
                        outcome="success",
                        view_revision=execution.view_revision,
                        event_refs=execution.public_event_refs,
                        narration_evidence=execution.narration_evidence,
                        committed_results=execution.committed_results,
                    ),
                ),
                player_view=player_view,
                allowed_evidence_refs=execution.public_event_refs,
                narration_evidence=execution.narration_evidence,
            )
        )
        self.assertEqual(
            narration.text,
            "水晶碎裂后，覆盖度假村的微光与雾气开始消散。",
        )

        finished = self.store.inspect_state(ROOM)
        self.assertTrue(finished.core_resolved)
        self.assertTrue(finished.ending_available)
        self.assertLessEqual(
            {"crystal_destroyed", "victims_released", "james_returns_home"},
            set(finished.discovered_facts),
        )
        self.assertIs(finished.entities["dream_crystal"]["broken"], True)
        self.assertIs(finished.entities["james"]["released"], True)
        self.assertIs(finished.entities["james"]["under_forced_custody"], False)
        self.assertIs(finished.entities["james"]["accompanying_party"], False)

    async def test_james_forced_custody_carry_and_drop_are_distinct_states(self) -> None:
        await self.reach_reception()
        initial = self.store.inspect_state(ROOM).entities["james"]
        self.assertEqual(
            initial,
            {
                "released": False,
                "under_forced_custody": False,
                "accompanying_party": False,
                "alive": True,
            },
        )

        await self.choose(
            "force_james_against_his_will",
            "force-james",
            "restrain",
            "entity",
            "james",
        )
        restrained = self.store.inspect_state(ROOM).entities["james"]
        self.assertIs(restrained["under_forced_custody"], True)
        self.assertIs(restrained["accompanying_party"], False)
        self.assertIs(restrained["alive"], True)
        self.assertEqual(self.store.inspect_state(ROOM).scene_id, "resort_reception")
        self.assertFalse(self.store.inspect_state(ROOM).core_resolved)
        self.assertFalse(self.store.inspect_state(ROOM).ending_available)

        await self.choose(
            "carry_james_against_his_will",
            "carry-james",
            "carry",
            "entity",
            "james",
        )
        carried = self.store.inspect_state(ROOM).entities["james"]
        self.assertIs(carried["under_forced_custody"], True)
        self.assertIs(carried["accompanying_party"], True)

        await self.choose(
            "stop_carrying_james",
            "stop-carrying-james",
            "drop",
            "entity",
            "james",
        )
        dropped = self.store.inspect_state(ROOM).entities["james"]
        self.assertIs(dropped["under_forced_custody"], True)
        self.assertIs(dropped["accompanying_party"], False)

        await self.choose(
            "release_james_from_forced_custody",
            "release-james",
            "release",
            "entity",
            "james",
        )
        released_from_custody = self.store.inspect_state(ROOM).entities["james"]
        self.assertIs(released_from_custody["under_forced_custody"], False)
        self.assertIs(released_from_custody["accompanying_party"], False)

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
            "force_james_out_of_resort",
            "force-james-out",
            "force",
            "entity",
            "james",
        )
        finished = self.store.inspect_state(ROOM)
        self.assertEqual(finished.scene_id, "outside")
        self.assertTrue(finished.core_resolved)
        self.assertTrue(finished.ending_available)
        self.assertIs(finished.entities["james"]["released"], False)
        self.assertIs(finished.entities["james"]["under_forced_custody"], True)
        self.assertIs(finished.entities["james"]["accompanying_party"], True)
        self.assertEqual(finished.entities["james"]["location_id"], "outside")
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
        self.assertIn("messenger_leaves_at_night", current.discovered_facts)
        entered = [
            event.payload["point_id"]
            for event in self.store.inspect_domain_events(ROOM)
            if event.type == "time.point_entered"
        ]
        self.assertEqual(entered, ["hour_18", "hour_22"])

    async def test_messenger_is_at_pond_when_visited_at_night_and_returns_by_day(self) -> None:
        await self.reach_reception()
        await self.advance("hour_18")
        await self.move("frog_pond")

        at_ritual = self.store.inspect_state(ROOM)
        self.assertEqual(at_ritual.entities["messenger"]["location_id"], "frog_pond")

        await self.advance("hour_22")
        await self.advance("hour_08")
        by_day = self.store.inspect_state(ROOM)
        self.assertIs(by_day.entities["night_ritual"]["active"], False)
        self.assertEqual(
            by_day.entities["messenger"]["location_id"], "resort_reception"
        )

    async def test_failed_follow_can_recover_by_visiting_and_observing_messenger(self) -> None:
        await self.reach_reception()
        await self.advance("hour_18")
        self.engine = AdjudicationEngineService(
            self.store,
            dice=DiceRoller(SequenceDiceSource([99, 5])),
        )

        failed = await self.choose(
            "follow_messenger_to_pond",
            "spot-hidden",
            "follow",
            "entity",
            "messenger",
            check_skill="spot-hidden",
        )
        self.assertEqual(failed.outcome, "failure")

        await self.move("frog_pond")
        arrived = self.store.inspect_state(ROOM)
        self.assertEqual(arrived.entities["messenger"]["location_id"], "frog_pond")

        observed = await self.choose(
            "observe_messenger_at_night_ritual",
            "spot-hidden",
            "observe",
            "entity",
            "messenger",
            check_skill="spot-hidden",
        )
        self.assertEqual(observed.outcome, "success")
        current = self.store.inspect_state(ROOM)
        self.assertIn("night_ritual_seen", current.discovered_facts)
        self.assertIn("crystal_is_power_core", current.discovered_facts)
        self.assertIs(current.entities["dream_crystal"]["known"], True)

    async def test_following_messenger_reaches_and_reveals_night_ritual(self) -> None:
        await self.reach_reception()
        await self.advance("hour_18")
        await self.choose(
            "follow_messenger_to_pond",
            "spot-hidden",
            "follow",
            "entity",
            "messenger",
            check_skill="spot-hidden",
        )

        current = self.store.inspect_state(ROOM)
        self.assertEqual(current.scene_id, "frog_pond")
        self.assertIn("messenger_leaves_at_night", current.discovered_facts)
        self.assertIn("night_ritual_seen", current.discovered_facts)
        self.assertIn("crystal_is_power_core", current.discovered_facts)
        self.assertIs(current.entities["dream_crystal"]["known"], True)

    async def test_night_ritual_to_crystal_destruction_lets_james_leave_safely(
        self,
    ) -> None:
        await self.reach_reception()
        await self.advance("hour_18")
        await self.choose(
            "follow_messenger_to_pond",
            "spot-hidden",
            "follow",
            "entity",
            "messenger",
            check_skill="spot-hidden",
        )
        await self.choose(
            "retrieve_dream_crystal",
            "swim",
            "retrieve",
            "entity",
            "dream_crystal",
            check_skill="swim",
        )

        retrieved = self.store.inspect_state(ROOM)
        self.assertEqual(retrieved.scene_id, "crystal_shore")
        self.assertIs(retrieved.entities["dream_crystal"]["retrieved"], True)
        self.assertEqual(
            retrieved.entities["dream_crystal"]["location_id"],
            "crystal_shore",
        )

        await self.choose(
            "destroy_dream_crystal",
            "break-crystal",
            "destroy",
            "entity",
            "dream_crystal",
        )
        resolved = self.store.inspect_state(ROOM)
        self.assertIs(resolved.entities["dream_crystal"]["broken"], True)
        self.assertIs(resolved.entities["james"]["released"], True)
        self.assertIs(resolved.entities["james"]["under_forced_custody"], False)
        self.assertIs(resolved.entities["james"]["accompanying_party"], False)
        self.assertIn("james_returns_home", resolved.discovered_facts)

        for location_id in (
            "frog_pond",
            "frog_resort",
            "resort_reception",
            "frog_resort",
            "resort_boundary",
            "outside",
        ):
            await self.move(location_id)

        finished = self.store.inspect_state(ROOM)
        self.assertEqual(finished.scene_id, "outside")
        self.assertIs(finished.entities["james"]["alive"], True)
        self.assertNotIn("james_forced_removal_tragedy", finished.discovered_facts)

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
