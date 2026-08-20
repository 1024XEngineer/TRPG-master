"""验证《林隙的罪恶》多人预设的内容身份、来源覆盖和运行能力门禁。"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionMethod,
    ActionTarget,
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
    / "docs/module-parser/examples/module-content-validation/林隙的罪恶"
)
FIXTURE = FIXTURE_DIR / "module-content-v3.json"


class LinxiContentGateTests(unittest.TestCase):
    """用最小、可重复的门禁阻止内容文件退回草稿或泄露 Keeper 文本。"""

    @classmethod
    def setUpClass(cls) -> None:
        cls.content = ModuleContentV3.model_validate_json(
            FIXTURE.read_text(encoding="utf-8")
        )

    def test_identity_and_runtime_capabilities(self) -> None:
        self.assertEqual(self.content.module_id, "linxi-sins-zh-coc7")
        self.assertEqual(self.content.version, "3.0.0")
        self.assertEqual(
            (
                self.content.presentation.players_min,
                self.content.presentation.players_max,
            ),
            (1, 3),
        )
        self.assertEqual(validate_module_v3(self.content).status, "pass")
        self.assertEqual(audit_runtime_capabilities(self.content), ())

    def test_all_locations_are_reachable_and_provenance_is_complete(self) -> None:
        adjacency: dict[str, list[str]] = {}
        for edge in self.content.location_edges:
            adjacency.setdefault(edge.from_location_id, []).append(edge.to_location_id)
        reached = {self.content.initial_state.start_location_id}
        frontier = list(reached)
        while frontier:
            for location_id in adjacency.get(frontier.pop(), []):
                if location_id not in reached:
                    reached.add(location_id)
                    frontier.append(location_id)
        self.assertEqual(reached, {location.id for location in self.content.locations})

        provenance = json.loads(
            (FIXTURE_DIR / "module-content-provenance.json").read_text(encoding="utf-8")
        )
        for collection in (
            "locations",
            "information",
            "rules",
            "knowledge_goals",
            "ending_anchors",
        ):
            ids = {item.id for item in getattr(self.content, collection)}
            self.assertEqual(ids, set(provenance[collection]))
            self.assertTrue(
                all(
                    provenance[collection][item_id]["doc_paragraphs"] for item_id in ids
                )
            )

    def test_keeper_text_is_not_in_player_intro_and_full_source_is_preserved(
        self,
    ) -> None:
        source = (FIXTURE_DIR / "林隙的罪恶-Butterrr.txt").read_text(encoding="utf-8")
        self.assertGreater(len(self.content.background), 7000)
        self.assertIn("守密人信息", self.content.background)
        intro = "\n".join(
            page.content for page in self.content.presentation.player_intro_pages
        )
        self.assertNotIn("夏盖妖虫在以扫脑内", intro)
        self.assertIn("作者的话", source)

    def test_rules_use_only_supported_effects_and_checks(self) -> None:
        serialized_payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
        serialized_payload.pop("background", None)
        serialized = json.dumps(serialized_payload, ensure_ascii=False)
        for forbidden in (
            "inventory.has",
            "ensure_runtime_entity",
            "commit_terminal_ending",
        ):
            self.assertNotIn(forbidden, serialized)
        steps = [step for rule in self.content.rules for step in rule.execution.steps]
        self.assertIn("adjudicated_check", {step.kind for step in steps})
        self.assertIn("check", {step.kind for step in steps})


class LinxiRuntimeSmokeTests(unittest.IsolatedAsyncioTestCase):
    """用真实裁决与规则服务跑通进入木屋、潜行逃生和终局事实提交。"""

    async def test_enter_and_escape_mainline(self) -> None:
        content = ModuleContentV3.model_validate_json(
            FIXTURE.read_text(encoding="utf-8")
        )
        room_id, player_id, actor_id = "linxi-smoke-room", "linxi-player", "linxi-actor"
        initial = create_initial_game_state(
            content,
            room_id=room_id,
            actors={
                actor_id: ActorState(
                    player_id=player_id,
                    name="测试调查员",
                    source_character_id="c",
                    source_character_version=1,
                    state={"skills": {"stealth": 80}},
                )
            },
        )
        store = InMemoryEngineStore()
        store.register_room(module_content=content, initial_state=initial)
        rules = RuleEngineService(store)
        engine = AdjudicationEngineService(
            store, dice=DiceRoller(SequenceDiceSource([1] * 8))
        )

        view = await rules.read(
            PlayerViewScope(room_id=room_id, player_id=player_id, actor_id=actor_id)
        )
        await engine.submit(
            SubmitAdjudicationRequest(
                room_id=room_id,
                player_id=player_id,
                adjudication=ActionAdjudication(
                    request_id="enter",
                    source_revision=view.revision,
                    actor_id=actor_id,
                    summary="进入木屋",
                    target=ActionTarget(kind="location", id="cabin"),
                    method=ActionMethod(family="enter", description="进入"),
                    rule_decision=RuleDecisionRef(
                        rule_id="enter_cabin", option_id="enter-cabin"
                    ),
                    check=NoAdjudicationCheck(),
                    success_effects=(),
                    failure_effects=(),
                ),
            )
        )
        view = await rules.read(
            PlayerViewScope(room_id=room_id, player_id=player_id, actor_id=actor_id)
        )
        pending = await engine.submit(
            SubmitAdjudicationRequest(
                room_id=room_id,
                player_id=player_id,
                adjudication=ActionAdjudication(
                    request_id="escape",
                    source_revision=view.revision,
                    actor_id=actor_id,
                    summary="潜行逃生",
                    target=ActionTarget(kind="entity", id="bell_fence"),
                    method=ActionMethod(family="escape", description="潜行"),
                    rule_decision=RuleDecisionRef(
                        rule_id="escape_house", option_id="escape-house"
                    ),
                    check=RequiredAdjudicationCheck(
                        candidates=(
                            SkillCheckCandidate(
                                candidate_id="escape-house",
                                skill_id="stealth",
                                difficulty="regular",
                                method_summary="潜行",
                                player_safe_reason="逃离铃铛围栏",
                            ),
                        )
                    ),
                    success_effects=(),
                    failure_effects=(),
                ),
            )
        )
        selected = await engine.decide(
            CheckDecisionRequest(
                request_id="escape-select",
                room_id=room_id,
                player_id=player_id,
                source_revision=pending.view_revision,
                decision_id=pending.pending_decision.decision_id,
                decision_version=pending.pending_decision.decision_version,
                choice=SelectCheckChoice(candidate_id="escape-house"),
            )
        )
        await engine.decide_post_roll(
            PostRollDecisionRequest(
                request_id="escape-accept",
                room_id=room_id,
                player_id=player_id,
                source_revision=selected.view_revision,
                check_id=selected.check_run.check_id,
                check_version=selected.check_run.version,
                option_id="accept-current",
            )
        )
        state = store.inspect_state(room_id)
        self.assertEqual(state.scene_id, "cabin")
        self.assertTrue(state.core_resolved)
        self.assertTrue(state.ending_available)
        self.assertIn("investigator_escaped", state.discovered_facts)


if __name__ == "__main__":
    unittest.main()
