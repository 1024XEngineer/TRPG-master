from __future__ import annotations

import asyncio
import unittest
from pathlib import Path

from collaboration_framework.bootstrap import build_fake_application
from collaboration_framework.contracts import PlayerInput
from collaboration_framework.engine import GameState
from collaboration_framework.module import validate_module_json


ROOT = Path(__file__).resolve().parents[1]
CAPABILITY_CASES = ROOT / "fixtures" / "capability-cases"


class ModuleCapabilityTests(unittest.TestCase):
    @unittest.expectedFailure
    def test_action_does_not_execute_on_scene_enter_rule(self) -> None:
        """Known Runtime gap: action lookup currently ignores Rule.hook."""

        report = validate_module_json(
            (CAPABILITY_CASES / "rule-hook-on-scene-enter.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report.status, "pass")
        self.assertIsNotNone(report.content)

        initial_state = GameState.model_validate(
            {
                "room_id": "hook_audit_room",
                "scene_id": "study",
                "actors": {
                    "investigator": {
                        "player_id": "hook_audit_player",
                        "name": "调查员",
                    }
                },
                "entities": {
                    "cabinet": {
                        "scene_ready": True,
                        "opened": False,
                    }
                },
            }
        )
        open_cabinet = PlayerInput(
            room_id="hook_audit_room",
            player_id="hook_audit_player",
            actor_id="investigator",
            client_action_id="hook_audit_open_001",
            utterance="我打开柜子。",
        )
        application = build_fake_application(report.content, initial_state)

        output = asyncio.run(application.orchestrator.run(open_cabinet))

        final_state = application.engine.snapshot()
        execution = application.engine.execution_for("hook_audit_open_001")
        self.assertEqual(output.action_result.resolution, "blocked")
        self.assertEqual(output.action_result.outcome, "not_applicable")
        self.assertFalse(final_state.entities["cabinet"]["opened"])
        self.assertEqual(execution.events, ())

    def test_checkpoint_failure_consumes_all_outcome_fields(self) -> None:
        report = validate_module_json(
            (CAPABILITY_CASES / "checkpoint-failure.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(report.status, "pass")
        self.assertIsNotNone(report.content)

        initial_state = GameState.model_validate(
            {
                "room_id": "failure_room",
                "scene_id": "study",
                "actors": {
                    "investigator": {
                        "player_id": "failure_player",
                        "name": "调查员",
                    }
                },
                "entities": {"bookshelf": {"searched": False}},
            }
        )
        player_input = PlayerInput(
            room_id="failure_room",
            player_id="failure_player",
            actor_id="investigator",
            client_action_id="failed_search_001",
            utterance="我仔细调查书架。",
        )
        application = build_fake_application(report.content, initial_state)

        output = asyncio.run(application.orchestrator.run(player_input))

        execution = application.engine.execution_for("failed_search_001")
        final_state = application.engine.snapshot()
        self.assertEqual(output.intent.check.checkpoint_id, "failed_search")
        self.assertEqual(output.action_result.resolution, "checkpoint")
        self.assertEqual(output.action_result.outcome, "failure")
        self.assertTrue(final_state.entities["bookshelf"]["searched"])
        self.assertEqual(
            [
                (
                    event.payload.path,
                    event.payload.from_value,
                    event.payload.to,
                    event.cause,
                )
                for event in execution.events
            ],
            [
                (
                    "entities.bookshelf.searched",
                    False,
                    True,
                    "checkpoint:failed_search",
                )
            ],
        )
        self.assertEqual(
            execution.confirmed_facts,
            ("玩家搜索了书架但没有找到线索",),
        )
        self.assertEqual(
            [fact.text for fact in output.action_result.visible_facts],
            ["你翻查了书架，却没有找到有用的线索。"],
        )
        self.assertEqual(
            output.action_result.narration_constraints,
            ("不得声称玩家发现了隐藏线索",),
        )
        self.assertEqual(
            output.narration.text,
            "你翻查了书架，却没有找到有用的线索。",
        )
        serialized_output = output.model_dump_json()
        self.assertNotIn("不应消费的成功事实", serialized_output)
        self.assertNotIn("不应显示的成功信息", serialized_output)
        self.assertNotIn("不应使用的成功叙事约束", serialized_output)

    def test_rule_allows_action_after_checkpoint_changes_state(self) -> None:
        report = validate_module_json(
            (
                CAPABILITY_CASES / "rule-allow-after-state-change.json"
            ).read_text(encoding="utf-8")
        )
        self.assertEqual(report.status, "pass")
        self.assertIsNotNone(report.content)

        initial_state = GameState.model_validate(
            {
                "room_id": "capability_room",
                "scene_id": "study",
                "actors": {
                    "investigator": {
                        "player_id": "capability_player",
                        "name": "调查员",
                    }
                },
                "entities": {
                    "bookshelf": {"key_found": False},
                    "cabinet": {"opened": False},
                },
            }
        )
        investigate = PlayerInput(
            room_id="capability_room",
            player_id="capability_player",
            actor_id="investigator",
            client_action_id="find_key_001",
            utterance="我仔细调查书架。",
        )
        application = build_fake_application(report.content, initial_state)

        investigate_output = asyncio.run(application.orchestrator.run(investigate))

        after_investigate = application.engine.snapshot()
        investigate_execution = application.engine.execution_for("find_key_001")
        self.assertEqual(
            investigate_output.intent.check.checkpoint_id,
            "find_key",
        )
        self.assertTrue(after_investigate.entities["bookshelf"]["key_found"])
        self.assertFalse(after_investigate.entities["cabinet"]["opened"])
        self.assertEqual(
            [event.payload.path for event in investigate_execution.events],
            ["entities.bookshelf.key_found"],
        )

        open_cabinet = investigate.model_copy(
            update={
                "client_action_id": "open_cabinet_001",
                "utterance": "我用钥匙打开木柜。",
            }
        )
        open_output = asyncio.run(application.orchestrator.run(open_cabinet))

        final_state = application.engine.snapshot()
        open_execution = application.engine.execution_for("open_cabinet_001")
        self.assertEqual(open_output.intent.verb, "open")
        self.assertEqual(open_output.action_result.resolution, "direct")
        self.assertEqual(open_output.action_result.outcome, "success")
        self.assertTrue(final_state.entities["cabinet"]["opened"])
        self.assertEqual(
            [
                (event.payload.path, event.cause)
                for event in open_execution.events
            ],
            [
                (
                    "entities.cabinet.opened",
                    "rule:allow_open_after_key_found",
                )
            ],
        )


if __name__ == "__main__":
    unittest.main()
