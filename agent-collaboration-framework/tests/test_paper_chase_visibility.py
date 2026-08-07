from __future__ import annotations

import json
import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ModuleContent,
    PlayerInput,
)
from collaboration_framework.engine import (
    ActorState,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
)
from collaboration_framework.host.application import PlayerViewProjector

ROOT = Path(__file__).resolve().parents[1]
PAPER_CHASE = (
    ROOT
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
    / "追书人"
    / "module-content-draft.json"
)


class PaperChaseVisibilityTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = ModuleContent.model_validate_json(
            PAPER_CHASE.read_text(encoding="utf-8")
        )

    def state(
        self,
        scene_id: str,
        *,
        updates: dict[str, dict[str, object]] | None = None,
        discovered: tuple[str, ...] = (),
    ) -> GameState:
        entities = {
            entity.id: dict(entity.state)
            for entity in self.module.entities
        }
        for entity_id, values in (updates or {}).items():
            entities[entity_id].update(values)
        return GameState(
            room_id=f"room-{scene_id}",
            scene_id=scene_id,
            actors={
                "investigator": ActorState(
                    player_id="player",
                    name="调查员",
                    source_character_id="character",
                    source_character_version=1,
                    state={"skills": {"spot-hidden": 60, "intimidate": 50}},
                )
            },
            entities=entities,
            discovered_facts=discovered,
        )

    async def view(
        self,
        scene_id: str,
        *,
        updates: dict[str, dict[str, object]] | None = None,
        discovered: tuple[str, ...] = (),
    ):
        state = self.state(scene_id, updates=updates, discovered=discovered)
        store = InMemoryEngineStore()
        store.register_room(module_content=self.module, initial_state=state)
        service = RuleEngineService(store)
        return await PlayerViewProjector(service).project(
            PlayerInput(
                room_id=state.room_id,
                player_id="player",
                actor_id="investigator",
                client_action_id="view",
                utterance="查看当前场景",
            )
        )

    @staticmethod
    def ids(items) -> set[str]:
        return {item.id for item in items}

    async def test_cemetery_visibility_matrix(self) -> None:
        initial = await self.view("cemetery")
        self.assertEqual(self.ids(initial.scene.visible_entities), {"melodias"})
        self.assertEqual(
            self.ids(initial.checkpoint_options),
            {"impress_caretaker", "observe_caretaker"},
        )
        self.assertEqual(
            self.ids(initial.scene.available_exits),
            {
                "client_briefing",
                "neighborhood",
                "library",
                "newspaper_office",
                "kimball_house",
            },
        )
        self.assertEqual(initial.scene.visible_entities[0].narrative_details, ())

        bottle = await self.view(
            "cemetery",
            updates={"melodias": {"bottle_noticed": True}},
        )
        melodias = bottle.scene.visible_entities[0]
        self.assertEqual(
            self.ids(melodias.narrative_details),
            {"melodias_pocket_bottle"},
        )
        self.assertIn("intimidate_caretaker", self.ids(bottle.checkpoint_options))
        self.assertIn("seek_liquor_contacts", self.ids(bottle.scene.available_exits))

        grave = await self.view(
            "cemetery",
            updates={"favorite_grave": {"identified": True}},
        )
        self.assertEqual(
            self.ids(grave.scene.visible_entities),
            {"melodias", "favorite_grave"},
        )
        self.assertIn("inspect_grave_area", self.ids(grave.checkpoint_options))

        entrance = await self.view(
            "cemetery",
            updates={"crypt_entrance": {"discovered": True}},
        )
        self.assertEqual(
            self.ids(entrance.scene.visible_entities),
            {"melodias", "crypt_entrance"},
        )
        self.assertIn(
            "approach_discovered_slab",
            self.ids(entrance.scene.available_exits),
        )

    async def test_diary_does_not_identify_the_favorite_grave(self) -> None:
        study = await self.view("kimball_house")
        self.assertNotIn("douglas_diary", self.ids(study.scene.visible_entities))
        self.assertNotIn("read_douglas_diary", self.ids(study.checkpoint_options))

        found = await self.view(
            "kimball_house",
            updates={"douglas_diary": {"found": True}},
        )
        self.assertIn("douglas_diary", self.ids(found.scene.visible_entities))
        self.assertIn("read_douglas_diary", self.ids(found.checkpoint_options))

        cemetery = await self.view(
            "cemetery",
            updates={"douglas_diary": {"found": True, "read": True}},
            discovered=("diary_tunnel_clue",),
        )
        self.assertNotIn("favorite_grave", self.ids(cemetery.scene.visible_entities))
        self.assertNotIn("inspect_grave_area", self.ids(cemetery.checkpoint_options))
        self.assertEqual(
            self.ids(cemetery.known_information),
            {"diary_tunnel_clue"},
        )

    async def test_visible_crypt_checkpoint_projects_declaration_options(
        self,
    ) -> None:
        crypt = await self.view(
            "crypt",
            updates={
                "crypt_entrance": {
                    "discovered": True,
                    "slab_moved": True,
                }
            },
        )

        option = next(
            item for item in crypt.checkpoint_options if item.id == "enter_crypt"
        )
        self.assertEqual(option.action_hint, "enter")
        self.assertEqual(
            [
                (item.id, item.semantic_hints)
                for item in option.declaration_options
            ],
            [
                (
                    "hold_breath",
                    ("屏住呼吸", "憋气", "hold breath"),
                )
            ],
        )

    async def test_night_watch_and_ghoul_reveal_matrix(self) -> None:
        waiting = await self.view(
            "night_surveillance",
            updates={"case_tracker": {"surveillance_available": True}},
        )
        self.assertEqual(
            self.ids(waiting.scene.visible_entities),
            {"surveillance_area", "study_window", "missing_books"},
        )
        self.assertEqual(
            self.ids(waiting.checkpoint_options),
            {"keep_night_watch"},
        )

        sighted = await self.view(
            "night_surveillance",
            updates={
                "case_tracker": {"surveillance_available": True},
                "cemetery_figure": {"sighted": True, "visit_observed": True},
            },
        )
        figure = next(
            entity
            for entity in sighted.scene.visible_entities
            if entity.id == "cemetery_figure"
        )
        self.assertEqual(figure.name, "墓地中的人影")
        self.assertNotIn("道格拉斯", figure.name)
        self.assertEqual(
            self.ids(sighted.checkpoint_options),
            {"keep_night_watch", "call_to_figure"},
        )

        confrontation = await self.view(
            "ghoul_confrontation",
            updates={
                "cemetery_figure": {"corpse_identified": True},
                "ghoul_crowd": {"revealed": True},
            },
        )
        self.assertEqual(
            self.ids(confrontation.scene.visible_entities),
            {"cemetery_figure", "ghoul_crowd"},
        )
        self.assertEqual(
            self.ids(confrontation.checkpoint_options),
            {"flee_ghoul_crowd"},
        )

    async def test_initial_views_do_not_contain_hidden_truth_or_semantic_ids(
        self,
    ) -> None:
        views = [
            await self.view("cemetery"),
            await self.view("kimball_house"),
            await self.view(
                "night_surveillance",
                updates={"case_tracker": {"surveillance_available": True}},
            ),
        ]
        serialized = json.dumps(
            [view.to_json_dict() for view in views],
            ensure_ascii=False,
        )
        for forbidden in (
            "caretaker_bottle",
            "notice_caretaker_bottle",
            "track_crypt_entrance",
            "看守口袋里的玻璃瓶",
            "道格拉斯常坐的墓碑",
            "石板下的地穴入口",
            "公墓地下有神秘生物居住的隧道网络",
            "食尸鬼群",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, serialized)

