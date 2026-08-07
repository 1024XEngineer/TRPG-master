"""Projecting a v3 module (#212 §7 / §4 / §8).

Driven by the real 追书人 v3 fixture rather than a toy module, because the
things most likely to break — a gated crypt, a study that is a room, an entity
placed by `located_in` — only exist at that scale.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import ModuleContentV3, PlayerViewScope
from collaboration_framework.engine import (
    ActorState,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
)
from collaboration_framework.engine.projection_v3 import location_breadcrumbs

FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-v3.json"
)
ROOM = "room_v3"
ACTOR = "pc_1"
PLAYER = "player_v3"


def module() -> ModuleContentV3:
    return ModuleContentV3.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def game_state(content: ModuleContentV3, **overrides) -> GameState:
    base = {
        "room_id": ROOM,
        "scene_id": content.initial_state.start_location_id,
        "actors": {
            ACTOR: ActorState(
                player_id=PLAYER,
                name="陈探员",
                source_character_id="character_v3",
                source_character_version=1,
                state={"skills": {"spot-hidden": 60}, "occupation": "私家侦探"},
            )
        },
        "entities": {},
    }
    base.update(overrides)
    return GameState(**base)


class ProjectionV3Tests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.content = module()

    async def project(self, state: GameState):
        store = InMemoryEngineStore()
        store.register_room(module_content=self.content, initial_state=state)
        engine = RuleEngineService(store)
        return await engine.read(
            PlayerViewScope(room_id=ROOM, player_id=PLAYER, actor_id=ACTOR)
        )

    async def test_opening_location_projects_its_entities_and_exits(self) -> None:
        snapshot = await self.project(game_state(self.content))
        self.assertEqual(snapshot.scene_id, "thomas_office")
        # thomas is placed here by `located_in`, not by a Scene entity list.
        self.assertIn("thomas", {entity.id for entity in snapshot.scene.visible_entities})
        self.assertIn(
            "arnoldsburg_streets",
            {
                exit_.destination.scene_id
                for exit_ in snapshot.scene.available_exits
                if exit_.destination
            },
        )

    async def test_hidden_edges_stay_out_of_the_view(self) -> None:
        # The crypt and the speakeasy must not be advertised before they are found.
        state = game_state(self.content, scene_id="cemetery")
        snapshot = await self.project(state)
        destinations = {
            exit_.destination.scene_id
            for exit_ in snapshot.scene.available_exits
            if exit_.destination
        }
        self.assertNotIn("crypt", destinations)
        self.assertIn("surveillance_point", destinations)

    async def test_moving_an_entity_moves_where_it_is_projected(self) -> None:
        # `located_in` is the module's placement; runtime state overrides it, which
        # is what `move_entity` writes.
        state = game_state(
            self.content,
            scene_id="cemetery",
            entities={"douglas_diary": {"location_id": "cemetery"}},
        )
        snapshot = await self.project(state)
        self.assertIn(
            "douglas_diary",
            {entity.id for entity in snapshot.scene.visible_entities},
        )

    async def test_a_carried_entity_follows_the_actor(self) -> None:
        state = game_state(
            self.content,
            scene_id="cemetery",
            entities={"douglas_diary": {"holder_actor_id": ACTOR}},
        )
        snapshot = await self.project(state)
        self.assertIn(
            "douglas_diary",
            {entity.id for entity in snapshot.scene.visible_entities},
        )

    async def test_a_consumed_entity_disappears(self) -> None:
        state = game_state(
            self.content,
            scene_id="speakeasy",
            entities={"liquor": {"consumed": True}},
        )
        snapshot = await self.project(state)
        self.assertNotIn("liquor", {entity.id for entity in snapshot.scene.visible_entities})

    async def test_undiscovered_information_is_withheld(self) -> None:
        snapshot = await self.project(game_state(self.content))
        self.assertEqual(snapshot.known_information, ())

    async def test_released_information_shows_only_the_player_half(self) -> None:
        state = game_state(self.content, discovered_facts=("cemetery_dance_report",))
        snapshot = await self.project(state)
        released = next(
            item for item in snapshot.known_information if item.id == "cemetery_dance_report"
        )
        keeper_text = next(
            item.keeper_content
            for item in self.content.information
            if item.id == "cemetery_dance_report"
        )
        self.assertEqual(released.scope, "party")
        self.assertNotIn(keeper_text, released.content)

    async def test_world_block_carries_the_clock_and_ending_state(self) -> None:
        snapshot = await self.project(game_state(self.content))
        self.assertEqual(snapshot.world.elapsed_minutes, 0)
        self.assertFalse(snapshot.world.core_resolved)
        self.assertFalse(snapshot.world.ending_available)

    async def test_v3_publishes_no_checkpoint_options(self) -> None:
        # The candidate menu is produced per action by an agent_match Rule, not
        # published with the scene (#226 §2).
        snapshot = await self.project(game_state(self.content))
        self.assertEqual(snapshot.checkpoint_options, ())

    def test_breadcrumbs_follow_containment_not_reachability(self) -> None:
        trail = location_breadcrumbs(self.content, "kimball_study")
        self.assertEqual(
            [name for _, name in trail],
            ["阿诺兹堡", "金博尔宅", "道格拉斯的书房"],
        )

    async def test_entering_a_runtime_location_still_projects(self) -> None:
        # v2 raised "当前 Scene 不存在" here and bricked the room.
        state = game_state(
            self.content,
            scene_id="alley",
            runtime_locations={
                "alley": {"name": "后巷", "connected_location_id": "arnoldsburg_streets"}
            },
        )
        snapshot = await self.project(state)
        self.assertEqual(snapshot.scene_id, "alley")
        self.assertEqual(snapshot.scene.name, "后巷")


if __name__ == "__main__":
    unittest.main()
