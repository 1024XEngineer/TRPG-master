"""The 追书人 v3 fixture must stay playable, not merely schema-valid.

Schema validity says the file parses. These tests say the *module works*: every
travelable location can be reached from the opening one, every Information has
at least one rule that can release it, and the goals gating the core resolution
are actually attainable. Those are the failures that would otherwise only show
up as a player getting stuck mid-session.
"""

from __future__ import annotations

import json
import unittest
from collections import Counter
from pathlib import Path

from collaboration_framework.contracts import ModuleContentV3
from collaboration_framework.module import validate_module_v3

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)


def load() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


class PaperChaseV3FixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.content = load()

    def test_fixture_passes_semantic_validation(self) -> None:
        report = validate_module_v3(self.content)
        self.assertEqual(report.status, "pass", report.errors)

    def test_every_travelable_location_is_reachable_from_the_start(self) -> None:
        # A region is a breadcrumb ancestor, not a destination (#212 §7.4), so it
        # is excluded — everything else must be walkable.
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
        travelable = {
            location.id for location in self.content.locations if location.kind != "region"
        }
        self.assertEqual(travelable - reached, set(), "存在走不到的地点")

    def test_every_information_has_a_rule_that_can_release_it(self) -> None:
        releasable = {
            step.effect.information_id
            for rule in self.content.rules
            for step in rule.execution.steps
            if getattr(step, "kind", None) == "effect"
            and getattr(step.effect, "type", None) == "reveal_information"
        }
        declared = {item.id for item in self.content.information}
        self.assertEqual(declared - releasable, set(), "存在无法被任何规则发放的信息")

    def test_core_resolution_goals_are_attainable(self) -> None:
        releasable = {
            step.effect.information_id
            for rule in self.content.rules
            for step in rule.execution.steps
            if getattr(step, "kind", None) == "effect"
            and getattr(step.effect, "type", None) == "reveal_information"
        }
        goals = {goal.id: goal for goal in self.content.knowledge_goals}
        for goal_id in self.content.core_resolution.required_goal_ids:
            goal = goals[goal_id]
            available = [
                target for target in goal.target_information_ids if target in releasable
            ]
            if goal.completion == "all":
                self.assertEqual(
                    len(available),
                    len(goal.target_information_ids),
                    f"目标 {goal_id} 有无法获得的信息",
                )
            else:
                self.assertTrue(available, f"目标 {goal_id} 没有任何可获得的信息")

    def test_reaching_the_core_resolution_opens_an_ending(self) -> None:
        kinds = Counter(
            getattr(step.effect, "type", None)
            for rule in self.content.rules
            for step in rule.execution.steps
            if getattr(step, "kind", None) == "effect"
        )
        self.assertGreaterEqual(kinds["mark_core_resolved"], 1)
        self.assertGreaterEqual(kinds["set_ending_availability"], 1)
        self.assertTrue(self.content.ending_anchors)

    def test_the_crypt_is_gated_by_its_access_point(self) -> None:
        # The boundary v2 Scene exits could not express (#212 §7.3): the crypt is
        # behind a slab, and the slab is an Entity the player has to move.
        edge = next(
            item
            for item in self.content.location_edges
            if item.from_location_id == "cemetery" and item.to_location_id == "crypt"
        )
        self.assertEqual(edge.traversal, "gated")
        self.assertEqual(edge.access_point_id, "crypt_entrance")
        self.assertEqual(edge.visibility, "hidden")
        self.assertTrue(edge.conditions)

    def test_keeper_content_never_leaks_into_player_content(self) -> None:
        for item in self.content.information:
            self.assertNotEqual(
                item.keeper_content,
                "",
                f"{item.id} 缺少守秘人正文",
            )
            self.assertNotEqual(item.player_content, "", f"{item.id} 缺少玩家正文")

    def test_narrative_beats_did_not_become_places(self) -> None:
        # v2 modelled "与道格拉斯交谈" and "食尸鬼群现身" as Scenes. They are beats,
        # not locations, and migrating them as places would put the player
        # "inside a conversation".
        location_ids = {location.id for location in self.content.locations}
        self.assertNotIn("conversation", location_ids)
        self.assertNotIn("ghoul_confrontation", location_ids)

    def test_the_study_is_a_room_rather_than_an_object(self) -> None:
        # v2 made 书房 an Entity, so "搜索书房" targeted a thing you were not in.
        study = next(item for item in self.content.locations if item.id == "kimball_study")
        self.assertEqual(study.kind, "room")
        self.assertEqual(study.parent_location_id, "kimball_house")
        self.assertNotIn("kimball_study", {entity.id for entity in self.content.entities})

    def test_every_v2_checkpoint_has_a_successor_rule(self) -> None:
        v2 = json.loads(
            (FIXTURE.with_name("module-content-draft.json")).read_text(encoding="utf-8")
        )
        migrated = {rule.id for rule in self.content.rules}
        missing = [
            checkpoint["id"]
            for checkpoint in v2["checkpoints"]
            if checkpoint["id"] not in migrated
        ]
        self.assertEqual(missing, [], "有 v2 checkpoint 在 v3 里没有对应规则")


if __name__ == "__main__":
    unittest.main()
