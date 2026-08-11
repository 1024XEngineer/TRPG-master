"""Contract guards that outlived the v2 Host workflow.

This file used to drive the whole Orchestrator turn end to end. That workflow
went away with the Checkpoint runtime (#226); what stayed are the checks that
never depended on it — the shipped JSON is parseable, the exported schemas still
match their Pydantic source, and Intent keeps proposing checks without ever
carrying an execution. Those guard the contract surface v3 inherits.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from collaboration_framework.contracts import Intent, MatchedTarget, ModuleCheck
from collaboration_framework.schema_export import rendered_schemas
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]


def load_text(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class ContractGuardTests(unittest.TestCase):
    def test_all_json_files_are_valid(self) -> None:
        for path in sorted(ROOT.rglob("*.json")):
            with self.subTest(path=path.relative_to(ROOT)):
                self.assertIsNotNone(json.loads(path.read_text(encoding="utf-8")))

    def test_exported_schemas_match_pydantic_source(self) -> None:
        expected = rendered_schemas()
        self.assertEqual(len(expected), 27)
        self.assertIn("keeper-capability-view.schema.json", expected)
        self.assertIn("module-content-v3.schema.json", expected)
        self.assertIn("action-adjudication.schema.json", expected)
        self.assertIn("adjudication-execution.schema.json", expected)
        self.assertIn("action-plan.schema.json", expected)
        self.assertIn("action-plan-policy.schema.json", expected)
        self.assertIn("action-plan-progress.schema.json", expected)
        self.assertIn("get-adjudication-status-request.schema.json", expected)
        self.assertIn("adjudication-status.schema.json", expected)
        self.assertIn("cancel-action-plan-request.schema.json", expected)
        self.assertIn("host-agent-context.schema.json", expected)
        self.assertIn("host-agent-usage.schema.json", expected)
        self.assertIn("host-agent-event.schema.json", expected)
        self.assertNotIn("turn-state.schema.json", expected)
        self.assertNotIn("event.schema.json", expected)
        self.assertNotIn("summary-operation.schema.json", expected)
        for filename, content in expected.items():
            with self.subTest(filename=filename):
                self.assertEqual(load_text(f"schemas/{filename}"), content)

    def test_intent_keeps_check_proposal_but_has_no_execution(self) -> None:
        schema = Intent.model_json_schema()
        self.assertNotIn("execution", schema["properties"])
        intent = Intent.model_validate(
            {
                "kind": "action",
                "verb": "inspect_in_my_own_way",
                "target": {"matched": True, "id": "bookshelf"},
                "check": {
                    "route": "module",
                    "checkpoint_id": "investigate_bookshelf",
                    "proposed_skills": ["spot-hidden"],
                },
                "approach": "慢慢翻查书背",
                "summary": "调查书架",
            }
        )
        self.assertIsInstance(intent.target, MatchedTarget)
        self.assertIsInstance(intent.check, ModuleCheck)
        self.assertEqual(intent.check.checkpoint_id, "investigate_bookshelf")
        self.assertEqual(intent.verb, "inspect_in_my_own_way")

    def test_discriminated_target_rejects_ambiguous_shape(self) -> None:
        with self.assertRaises(ValidationError):
            Intent.model_validate(
                {
                    "kind": "action",
                    "verb": "open",
                    "target": {
                        "matched": True,
                        "id": "cabinet",
                        "raw": "柜子",
                    },
                    "check": {"route": "none"},
                    "summary": "打开柜子",
                }
            )

if __name__ == "__main__":
    unittest.main()
