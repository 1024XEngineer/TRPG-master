"""验证《常暗之厢》内容能由真实 v3 Runtime 回放核心分支。"""

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
    ActorResources,
    ActorState,
    AdjudicationEngineService,
    DiceRoller,
    InMemoryEngineStore,
    RuleEngineService,
    SequenceDiceSource,
    audit_runtime_capabilities,
)
from collaboration_framework.engine.initialization import create_initial_game_state
from collaboration_framework.engine.rules_v3 import (
    agent_match_admits,
    matching_event_rules,
)
from collaboration_framework.host.application import PlayerViewProjector
from collaboration_framework.module import validate_module_v3
from collaboration_framework.registry.effects import EFFECTS
from collaboration_framework.registry.rule_steps import STEP_KINDS

FIXTURE_DIR = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "常暗之厢"
)
FIXTURE = FIXTURE_DIR / "module-content-v3.json"
ROOM = "constant-darkness-room"
PLAYER = "constant-darkness-player"
ACTOR = "constant-darkness-actor"


def load_module() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def initial_state():
    skills = dict.fromkeys(
        (
            "idea",
            "medicine",
            "spot-hidden",
            "library-use",
            "first-aid",
            "persuade",
            "stealth",
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
                source_character_id="constant-darkness-character",
                source_character_version=1,
                state={"skills": skills, "attributes": {"STR": 80}},
                resources=ActorResources(san=60, luck=60),
            )
        },
    )


class ConstantDarknessContentGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.content = load_module()

    def test_schema_semantics_and_runtime_capabilities_pass(self) -> None:
        self.assertEqual(validate_module_v3(self.content).status, "pass")
        self.assertEqual(audit_runtime_capabilities(self.content), ())

    def test_every_review_object_has_provenance(self) -> None:
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

    def test_agent_rules_have_complete_natural_language_boundaries(self) -> None:
        for rule in self.content.rules:
            if rule.trigger.kind != "agent_match":
                continue
            scope = rule.trigger.scope
            self.assertTrue(scope.action_families, rule.id)
            self.assertTrue(scope.location_ids, rule.id)
            self.assertTrue(scope.target_kinds, rule.id)
            self.assertTrue(scope.target_ids, rule.id)
            self.assertTrue(rule.trigger.question.semantic_hints, rule.id)
            self.assertTrue(rule.trigger.options, rule.id)
            branch_ids = {branch.id for branch in rule.execution.branches}
            self.assertLessEqual({item.id for item in rule.trigger.options}, branch_ids)
            for hint in rule.trigger.question.semantic_hints:
                self.assertTrue(
                    any("\u4e00" <= char <= "\u9fff" for char in hint), (rule.id, hint)
                )

    def test_core_chinese_utterances_are_covered_by_published_hints(self) -> None:
        utterances = {
            "turn_warning_note_over": "我把便签撕下来翻到背面看看",
            "first_aid_attendant": "我先给重伤的乘务员做急救",
            "search_key_bag": "我在3号车厢前门附近翻找那个断带黑包",
            "distract_clickers_and_pass": "我把东西扔远制造声音，趁怪物被引开时通过",
            "accelerate_train": "我把右边的油门杆向下拉到底，让列车全速加速",
        }
        rules = {rule.id: rule for rule in self.content.rules}
        for rule_id, utterance in utterances.items():
            hints = rules[rule_id].trigger.question.semantic_hints
            self.assertTrue(
                any(hint in utterance or utterance in hint for hint in hints),
                (rule_id, utterance, hints),
            )

    def test_only_executable_steps_and_effects_are_authored(self) -> None:
        authored_steps = {
            step.kind for rule in self.content.rules for step in rule.execution.steps
        }
        authored_effects = {
            step.effect.type
            for rule in self.content.rules
            for step in rule.execution.steps
            if step.kind == "effect"
        }
        self.assertLessEqual(authored_steps, set(STEP_KINDS))
        self.assertLessEqual(authored_effects, set(EFFECTS))
        self.assertTrue(
            authored_steps.isdisjoint(
                {
                    "invoke_ruleset_action",
                    "create_npc_action_opportunity",
                    "presentation",
                    "await_player_input",
                }
            )
        )
        self.assertNotIn("narrative_only", authored_effects)
        self.assertNotIn("commit_terminal_ending", authored_effects)

    def test_hierarchy_regions_are_not_travel_nodes(self) -> None:
        region_ids = {
            item.id for item in self.content.locations if item.kind == "region"
        }
        endpoints = {
            endpoint
            for edge in self.content.location_edges
            for endpoint in (edge.from_location_id, edge.to_location_id)
        }
        self.assertTrue(region_ids.isdisjoint(endpoints))
        by_id = {item.id: item for item in self.content.locations}
        self.assertEqual(by_id["driver_cab"].parent_location_id, "dream_train")
        self.assertIn("驾驶室", by_id["driver_cab"].aliases)

    def test_all_non_region_locations_are_structurally_reachable(self) -> None:
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
        expected = {item.id for item in self.content.locations if item.kind != "region"}
        self.assertEqual(reached, expected)

    def test_check_routes_respect_declared_difficulty(self) -> None:
        for rule in self.content.rules:
            for step in rule.execution.steps:
                if (
                    step.kind != "check"
                    or step.check.initiation_kind != "active_action"
                ):
                    continue
                difficulty = step.check.difficulty or "regular"
                if difficulty == "hard":
                    self.assertNotEqual(
                        step.result_routes["regular_success"],
                        step.result_routes["hard_success"],
                    )
                if difficulty == "extreme":
                    self.assertNotEqual(
                        step.result_routes["hard_success"],
                        step.result_routes["extreme_success"],
                    )
                self.assertIn("failure", step.result_routes)
                self.assertIn("fumble", step.result_routes)

    def test_player_presentation_does_not_reveal_keeper_truth(self) -> None:
        public = "\n".join(
            [
                self.content.background,
                self.content.presentation.synopsis,
                *(
                    page.content
                    for page in self.content.presentation.player_intro_pages
                ),
                *(item.player_visible_description for item in self.content.locations),
            ]
        )
        for secret in ("奈亚", "共同梦境", "对声音极其敏感", "3 号车厢前门附近"):
            self.assertNotIn(secret, public)

    def test_ending_rules_and_midnight_event_are_mutually_guarded(self) -> None:
        rules = {rule.id: rule for rule in self.content.rules}
        self.assertEqual(
            rules["midnight_maw_consumes_train"].trigger.event_type,
            "time.point_entered",
        )
        for rule_id in ("accelerate_train", "decelerate_train"):
            self.assertIsNotNone(rules[rule_id].trigger.when)
        serialized = FIXTURE.read_text(encoding="utf-8")
        self.assertGreaterEqual(serialized.count('"predicate": "core_resolved"'), 3)


class ConstantDarknessRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.content = load_module()
        self.store = InMemoryEngineStore()
        self.store.register_room(
            module_content=self.content, initial_state=initial_state()
        )
        self.engine = AdjudicationEngineService(
            self.store,
            dice=DiceRoller(SequenceDiceSource([5] * 80)),
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
        request_id = f"constant-darkness-{self.sequence}"
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
                    request_id=f"constant-darkness-travel-{self.sequence}",
                    source_revision=await self.revision(),
                    actor_id=ACTOR,
                    summary=f"前往 {location_id}",
                    target=ActionTarget(kind="location", id=location_id),
                    method=ActionMethod(family="travel", description="沿车厢前进"),
                    persistence_intent="location",
                    check=NoAdjudicationCheck(),
                    success_effects=(EnterLocationEffect(location_id=location_id),),
                ),
            )
        )

    async def advance_to_midnight(self) -> None:
        self.sequence += 1
        await self.engine.submit(
            SubmitAdjudicationRequest(
                room_id=ROOM,
                player_id=PLAYER,
                adjudication=ActionAdjudication(
                    request_id=f"constant-darkness-time-{self.sequence}",
                    source_revision=await self.revision(),
                    actor_id=ACTOR,
                    summary="等待到午夜",
                    target=ActionTarget(kind="world", id=self.content.world_ref),
                    method=ActionMethod(family="wait", description="让世界时间推进"),
                    check=NoAdjudicationCheck(),
                    success_effects=(AdvanceWorldTimeEffect(to_point_id="hour_00"),),
                ),
            )
        )

    async def reach_controls(self) -> None:
        await self.choose(
            "read_warning_note", "read-front", "read", "entity", "warning_note"
        )
        await self.choose(
            "turn_warning_note_over",
            "inspect-back",
            "inspect",
            "entity",
            "warning_note",
        )
        await self.move("car_5")
        await self.choose(
            "search_newspaper",
            "find-newspaper",
            "search",
            "location",
            "car_5",
            check_skill="spot-hidden",
        )
        await self.choose(
            "analyze_newspaper_date",
            "compare-date-and-report",
            "read",
            "entity",
            "newspaper",
            check_skill="library-use",
        )
        await self.move("car_4")
        await self.choose(
            "first_aid_attendant",
            "wake-attendant",
            "first-aid",
            "entity",
            "attendant",
            check_skill="first-aid",
        )
        await self.choose(
            "ask_attendant_about_attack",
            "ask-what-happened",
            "ask",
            "entity",
            "attendant",
        )
        await self.choose(
            "ask_attendant_about_attackers",
            "ask-attacker-features",
            "ask",
            "entity",
            "attendant",
        )
        await self.choose(
            "ask_attendant_about_keys",
            "ask-key-location",
            "ask",
            "entity",
            "attendant",
        )
        await self.move("car_3")
        await self.choose(
            "search_key_bag",
            "search-front-door-luggage",
            "search",
            "entity",
            "luggage_pile",
            check_skill="spot-hidden",
        )
        await self.choose(
            "distract_clickers_and_pass",
            "make-distant-noise",
            "distract",
            "entity",
            "clicker_group",
        )
        await self.choose(
            "unlock_cab_and_panel",
            "use-both-keys",
            "unlock",
            "entity",
            "cab_door",
        )
        await self.choose(
            "inspect_control_panel",
            "identify-levers",
            "inspect",
            "entity",
            "control_panel",
        )

    async def test_opening_projection_is_secret_safe_and_state_scoped(self) -> None:
        player_input = PlayerInput(
            client_action_id="opening-input",
            room_id=ROOM,
            player_id=PLAYER,
            actor_id=ACTOR,
            utterance="看看我醒来的车厢",
        )
        view = await PlayerViewProjector(self.rules).project(player_input)
        self.assertEqual(view.scene.id, "car_6")
        self.assertEqual(view.known_information, ())
        self.assertNotIn("rear_maw", {item.id for item in view.scene.visible_entities})
        capabilities = await self.rules.read_keeper_capabilities(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )
        self.assertEqual(
            {item.rule_id for item in capabilities.rule_candidates},
            {"read_warning_note", "inspect_route_map", "enter_rear_car"},
        )

    async def test_full_mainline_opens_accelerate_ending(self) -> None:
        await self.reach_controls()
        await self.choose(
            "accelerate_train",
            "push-throttle-down",
            "accelerate",
            "entity",
            "control_panel",
        )
        state = self.store.inspect_state(ROOM)
        self.assertEqual(state.scene_id, "terminal_train_car")
        self.assertTrue(state.core_resolved)
        self.assertTrue(state.ending_available)
        self.assertEqual(state.entities["train_chase"]["outcome"], "accelerate")
        self.assertEqual(state.entities["key_bag"]["location_id"], "terminal_train_car")
        self.assertLessEqual(
            {
                "warning_note_back",
                "newspaper_from_tomorrow",
                "clickers_follow_sound",
                "key_bag_location",
                "key_bag_retrieved",
                "clicker_car_crossed",
                "control_panel_instructions",
                "ending_accelerate",
            },
            set(state.discovered_facts),
        )
        accelerate = next(
            rule for rule in self.content.rules if rule.id == "accelerate_train"
        )
        decelerate = next(
            rule for rule in self.content.rules if rule.id == "decelerate_train"
        )
        for rule in (accelerate, decelerate):
            self.assertFalse(
                agent_match_admits(
                    rule,
                    state=state,
                    actor_id=ACTOR,
                    location_id=state.scene_id,
                )
            )

    async def test_decelerate_ending_opens_through_real_rule_effects(self) -> None:
        await self.reach_controls()
        await self.choose(
            "decelerate_train",
            "pull-throttle-up",
            "decelerate",
            "entity",
            "control_panel",
        )
        state = self.store.inspect_state(ROOM)
        self.assertEqual(state.scene_id, "terminal_train_car")
        self.assertEqual(state.entities["train_chase"]["outcome"], "decelerate")
        self.assertIn("ending_decelerate", state.discovered_facts)
        self.assertNotIn("ending_accelerate", state.discovered_facts)

    async def test_midnight_event_automatically_opens_consumed_ending(self) -> None:
        await self.advance_to_midnight()
        state = self.store.inspect_state(ROOM)
        self.assertEqual(state.world_time.current.day_index, 1)
        self.assertEqual(state.world_time.current_point_id, "hour_00")
        self.assertEqual(state.scene_id, "hospital_isolation")
        self.assertEqual(state.entities["train_chase"]["outcome"], "consumed")
        self.assertIs(state.entities["train_chase"]["deadline_reached"], True)
        self.assertIn("ending_consumed", state.discovered_facts)
        self.assertTrue(state.core_resolved)
        self.assertEqual(
            matching_event_rules(
                self.content,
                event_type="time.point_entered",
                state=state,
                actor_id=ACTOR,
            ),
            (),
        )

    async def test_key_search_failure_does_not_lock_retry(self) -> None:
        store = InMemoryEngineStore()
        store.register_room(module_content=self.content, initial_state=initial_state())
        self.store = store
        self.engine = AdjudicationEngineService(
            store,
            dice=DiceRoller(SequenceDiceSource([95, 5])),
        )
        self.rules = RuleEngineService(store)
        await self.move("car_5")
        await self.move("car_4")
        await self.move("car_3")
        await self.choose(
            "search_key_bag",
            "search-front-door-luggage",
            "search",
            "entity",
            "luggage_pile",
            check_skill="spot-hidden",
        )
        failed = store.inspect_state(ROOM)
        self.assertIs(failed.entities["key_bag"]["retrieved"], False)
        self.assertIn("key_search_can_continue", failed.discovered_facts)
        await self.choose(
            "search_key_bag",
            "search-front-door-luggage",
            "search",
            "entity",
            "luggage_pile",
            check_skill="spot-hidden",
        )
        retried = store.inspect_state(ROOM)
        self.assertIs(retried.entities["key_bag"]["retrieved"], True)
        self.assertIn("key_bag_retrieved", retried.discovered_facts)

    async def test_attendant_and_key_bag_move_with_the_party(self) -> None:
        await self.move("car_5")
        await self.move("car_4")
        await self.choose(
            "first_aid_attendant",
            "wake-attendant",
            "first-aid",
            "entity",
            "attendant",
            check_skill="first-aid",
        )
        await self.choose(
            "ask_attendant_about_attack",
            "ask-what-happened",
            "ask",
            "entity",
            "attendant",
        )
        await self.choose(
            "ask_attendant_about_attackers",
            "ask-attacker-features",
            "ask",
            "entity",
            "attendant",
        )
        await self.choose(
            "carry_attendant_to_car_3",
            "carry-forward",
            "carry",
            "entity",
            "attendant",
            check_skill="STR",
        )
        await self.choose(
            "persuade_attendant_to_hand_over_keys",
            "keep-key-bag",
            "persuade",
            "entity",
            "attendant",
            check_skill="persuade",
        )
        await self.choose(
            "distract_clickers_and_pass",
            "make-distant-noise",
            "distract",
            "entity",
            "clicker_group",
        )
        at_lead = self.store.inspect_state(ROOM)
        self.assertEqual(at_lead.entities["attendant"]["location_id"], "lead_car")
        self.assertEqual(at_lead.entities["key_bag"]["location_id"], "lead_car")
        await self.choose(
            "unlock_cab_and_panel",
            "use-both-keys",
            "unlock",
            "entity",
            "cab_door",
        )
        at_cab = self.store.inspect_state(ROOM)
        self.assertEqual(at_cab.entities["attendant"]["location_id"], "driver_cab")
        self.assertEqual(at_cab.entities["key_bag"]["location_id"], "driver_cab")

    async def test_rear_car_reveal_reaches_passive_sanity_check(self) -> None:
        execution = await self.choose(
            "enter_rear_car",
            "open-and-enter",
            "enter",
            "entity",
            "rear_door",
        )
        self.assertEqual(execution.status, "awaiting_skill_choice")
        pending = execution.pending_decision
        self.assertIsNotNone(pending)
        assert pending is not None
        self.assertEqual(pending.options[0].display_name, "理智")
        state = self.store.inspect_state(ROOM)
        self.assertEqual(state.scene_id, "car_7")
        self.assertIs(state.entities["horror_checks"]["bodies"], True)


if __name__ == "__main__":
    unittest.main()
