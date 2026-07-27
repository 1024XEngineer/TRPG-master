from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from collaboration_framework.bootstrap import build_fake_application
from collaboration_framework.contracts import ModuleContent, PlayerInput
from collaboration_framework.engine import GameState
from collaboration_framework.module import publish_module, validate_module_json

from tests.check_candidate_snapshots import DEMO_CHECK_CANDIDATES

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


class PublishedModuleRuntimeLoadTests(unittest.TestCase):
    def published_runtime_inputs(self):
        report = validate_module_json(
            (FIXTURES / "demo-module.json").read_text(encoding="utf-8"),
            skill_catalog=DEMO_CHECK_CANDIDATES,
        )
        self.assertEqual(report.status, "pass")

        with tempfile.TemporaryDirectory() as directory:
            published_path = Path(directory) / "module.json"
            publish_module(report, published_path)
            module_content = ModuleContent.model_validate_json(
                published_path.read_text(encoding="utf-8")
            )

        game_state = GameState.model_validate_json(
            (FIXTURES / "demo-state.json").read_text(encoding="utf-8")
        )
        player_input = PlayerInput.model_validate_json(
            (FIXTURES / "demo-turn.json").read_text(encoding="utf-8")
        )
        return module_content, game_state, player_input

    def test_published_json_loads_into_runtime_and_executes_checkpoint(self) -> None:
        module_content, game_state, player_input = self.published_runtime_inputs()
        application = build_fake_application(module_content, game_state)

        output = asyncio.run(application.orchestrator.run(player_input))
        snapshot = application.engine_store.inspect_state(game_state.room_id)

        self.assertEqual(output.action_result.resolution, "checkpoint")
        self.assertEqual(output.action_result.outcome, "success")
        self.assertTrue(snapshot.entities["bookshelf"]["key_found"])
        self.assertEqual(snapshot.event_sequence, 1)

    def test_published_module_checkpoint_reaches_win_condition(self) -> None:
        module_content, game_state, player_input = self.published_runtime_inputs()
        smash_input = player_input.model_copy(
            update={
                "client_action_id": "smash_published_001",
                "utterance": "我用力砸开柜子。",
            }
        )
        application = build_fake_application(module_content, game_state)

        output = asyncio.run(application.orchestrator.run(smash_input))

        snapshot = application.engine_store.inspect_state(game_state.room_id)
        self.assertEqual(output.action_result.resolution, "checkpoint")
        self.assertEqual(output.action_result.outcome, "success")
        self.assertTrue(snapshot.entities["cabinet"]["opened"])
        self.assertTrue(snapshot.entities["document"]["destroyed"])
        self.assertEqual(snapshot.ending_id, "ending_document_destroyed")
        self.assertEqual(snapshot.phase, "ended")
        self.assertEqual(snapshot.event_sequence, 4)

    def test_phase1_published_module_completes_sequential_runtime_flow(self) -> None:
        source_json = (FIXTURES / "demo-module.json").read_text(encoding="utf-8")
        report = validate_module_json(
            source_json,
            skill_catalog=DEMO_CHECK_CANDIDATES,
        )
        self.assertEqual(report.status, "pass")
        self.assertIsNotNone(report.content)

        with tempfile.TemporaryDirectory() as directory:
            published_path = Path(directory) / "module.json"
            publish_module(report, published_path)
            published_json = published_path.read_text(encoding="utf-8")
            self.assertNotEqual(published_json, source_json)
            published_module = ModuleContent.model_validate_json(published_json)

        self.assertEqual(published_module, report.content)
        initial_state = GameState.model_validate_json(
            (FIXTURES / "demo-state.json").read_text(encoding="utf-8")
        )
        investigate_input = PlayerInput.model_validate_json(
            (FIXTURES / "demo-turn.json").read_text(encoding="utf-8")
        )
        application = build_fake_application(published_module, initial_state)

        investigate_output = asyncio.run(
            application.orchestrator.run(investigate_input)
        )
        after_investigate = application.engine_store.inspect_state(
            initial_state.room_id
        )
        investigate_execution = application.engine_store.inspect_completed_action(
            initial_state.room_id,
            investigate_input.client_action_id
        ).execution

        self.assertEqual(after_investigate.scene_id, "study")
        self.assertEqual(
            investigate_output.intent.check.checkpoint_id,
            "investigate_bookshelf",
        )
        self.assertFalse(initial_state.entities["bookshelf"]["key_found"])
        self.assertTrue(after_investigate.entities["bookshelf"]["key_found"])
        self.assertEqual(
            [event.payload.path for event in investigate_execution.events],
            ["entities.bookshelf.key_found"],
        )
        self.assertEqual(
            [
                (
                    event.payload.from_value,
                    event.payload.to,
                    event.cause,
                )
                for event in investigate_execution.events
            ],
            [(False, True, "checkpoint:investigate_bookshelf")],
        )
        self.assertEqual(after_investigate.phase, "playing")
        self.assertIsNone(after_investigate.ending_id)

        smash_input = investigate_input.model_copy(
            update={
                "client_action_id": "smash_after_investigate_001",
                "utterance": "我用力砸开柜子。",
            }
        )
        smash_output = asyncio.run(application.orchestrator.run(smash_input))
        final_state = application.engine_store.inspect_state(initial_state.room_id)
        smash_execution = application.engine_store.inspect_completed_action(
            initial_state.room_id,
            smash_input.client_action_id
        ).execution

        self.assertEqual(final_state.scene_id, "study")
        self.assertEqual(
            smash_output.intent.check.checkpoint_id,
            "smash_cabinet",
        )
        self.assertFalse(after_investigate.entities["cabinet"]["opened"])
        self.assertFalse(after_investigate.entities["document"]["destroyed"])
        self.assertTrue(final_state.entities["cabinet"]["opened"])
        self.assertTrue(final_state.entities["document"]["destroyed"])
        self.assertEqual(
            [event.payload.path for event in smash_execution.events],
            [
                "entities.cabinet.opened",
                "entities.document.destroyed",
                "ending_id",
                "phase",
            ],
        )
        self.assertEqual(
            [event.event_id for event in investigate_execution.events],
            ["evt_0001"],
        )
        self.assertEqual(
            [event.event_id for event in smash_execution.events],
            ["evt_0002", "evt_0003", "evt_0004", "evt_0005"],
        )
        self.assertEqual(
            [event.cause for event in smash_execution.events],
            [
                "checkpoint:smash_cabinet",
                "checkpoint:smash_cabinet",
                "win_condition:ending_document_destroyed",
                "win_condition:ending_document_destroyed",
            ],
        )
        self.assertEqual(final_state.ending_id, "ending_document_destroyed")
        self.assertEqual(final_state.phase, "ended")
        self.assertEqual(final_state.event_sequence, 5)


if __name__ == "__main__":
    unittest.main()
