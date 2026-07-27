from __future__ import annotations

import json
import unittest
from pathlib import Path

from collaboration_framework.contracts import ModuleContent
from collaboration_framework.module import (
    validate_draft,
    validate_module,
    validate_module_json,
)
from collaboration_framework.module.models import ModuleDraft

from tests.check_candidate_snapshots import DEMO_CHECK_CANDIDATES

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
INVALID = FIXTURES / "invalid-modules"
PARSER_EXAMPLES = (
    ROOT / "docs" / "module-parser" / "examples" / "module-content-validation"
)


class ModuleValidationTests(unittest.TestCase):
    def test_valid_demo_returns_module_content(self) -> None:
        report = validate_module_json((FIXTURES / "demo-module.json").read_text())

        self.assertTrue(report.is_valid)
        self.assertEqual(report.status, "pass")
        self.assertEqual(report.errors, ())
        self.assertEqual(report.warnings, ())
        self.assertIsInstance(report.content, ModuleContent)
        self.assertEqual(report.content.module_id, "study-demo")

    def test_an_existing_module_content_is_accepted(self) -> None:
        content = ModuleContent.model_validate_json(
            (FIXTURES / "demo-module.json").read_text()
        )

        report = validate_module(content)

        self.assertTrue(report.is_valid)
        self.assertEqual(report.content, content)

    def test_full_parser_catalog_passes_draft_to_publication_boundary(self) -> None:
        report = validate_module_json(
            (FIXTURES / "module-content-v1-catalog.json").read_text(
                encoding="utf-8"
            )
        )

        self.assertTrue(report.is_valid)
        self.assertIsInstance(report.content, ModuleContent)

    def test_parser_example_drafts_match_the_current_structural_contract(self) -> None:
        paths = sorted(PARSER_EXAMPLES.glob("*/module-content-draft.json"))

        self.assertEqual(len(paths), 4)
        for path in paths:
            with self.subTest(module=path.parent.name):
                draft = ModuleDraft.model_validate_json(
                    path.read_text(encoding="utf-8")
                )
                self.assertTrue(draft.module_id)

    def test_negative_fixtures_have_stable_error_codes(self) -> None:
        cases = {
            "invalid-json.txt": "schema.invalid_json",
            "missing-field.json": "schema.missing_field",
            "extra-field.json": "schema.extra_field",
            "duplicate-id.json": "id.duplicate",
            "scene-entity-not-found.json": "scene.ref.entity_not_found",
            "scene-checkpoint-not-found.json": "scene.ref.checkpoint_not_found",
            "checkpoint-scene-not-found.json": "checkpoint.ref.scene_not_found",
            "checkpoint-target-not-found.json": "checkpoint.ref.target_not_found",
            "rule-state-path-not-found.json": "rule.ref.state_path_not_found",
            "operation-state-path-not-found.json": "operation.ref.state_path_not_found",
            "win-condition-state-path-not-found.json": (
                "win_condition.ref.state_path_not_found"
            ),
            "checkpoint-target-not-in-scene.json": (
                "checkpoint.ref.target_not_in_scene"
            ),
            "checkpoint-not-listed-in-scene.json": (
                "checkpoint.ref.not_listed_in_scene"
            ),
            "invalid-rule-hook.json": "rule.hook.unsupported",
        }

        for filename, expected_code in cases.items():
            with self.subTest(filename=filename):
                report = validate_module_json((INVALID / filename).read_text())
                self.assertFalse(report.is_valid)
                self.assertEqual(report.status, "needs_revision")
                self.assertIsNone(report.content)
                self.assertEqual(report.errors[0].code, expected_code)
                self.assertEqual(report.errors[0].severity, "error")
                self.assertTrue(report.errors[0].path)
                self.assertTrue(report.errors[0].message)

    def test_unknown_skill_is_rejected_against_injected_catalog(self) -> None:
        report = validate_module_json(
            (INVALID / "unknown-checkpoint-skill.json").read_text(),
            skill_catalog=DEMO_CHECK_CANDIDATES,
        )

        self.assertEqual(report.status, "needs_revision")
        self.assertEqual(report.errors[0].code, "checkpoint.ref.skill_not_found")

    def test_rule_ids_are_unique_across_the_module(self) -> None:
        payload = json.loads((FIXTURES / "demo-module.json").read_text())
        rule = payload["entities"][2]["rules"][0]
        payload["entities"][0]["rules"] = [rule]

        report = validate_module(payload)

        self.assertIn("id.duplicate", {issue.code for issue in report.errors})

    def test_multiple_semantic_errors_are_reported_together(self) -> None:
        draft = ModuleDraft.model_validate_json(
            (INVALID / "multiple-semantic-errors.json").read_text()
        )

        report = validate_draft(draft, skill_catalog=DEMO_CHECK_CANDIDATES)

        codes = {issue.code for issue in report.errors}
        self.assertEqual(report.status, "needs_revision")
        self.assertGreaterEqual(len(report.errors), 7)
        self.assertTrue(
            {
                "scene.ref.entity_not_found",
                "scene.ref.checkpoint_not_found",
                "checkpoint.ref.scene_not_found",
                "checkpoint.ref.target_not_found",
                "checkpoint.ref.skill_not_found",
                "rule.ref.state_path_not_found",
                "operation.ref.state_path_not_found",
                "win_condition.ref.state_path_not_found",
            }.issubset(codes)
        )

    def test_multiple_schema_errors_are_reported_together(self) -> None:
        report = validate_module({"unexpected": True})

        self.assertFalse(report.is_valid)
        self.assertGreater(len(report.errors), 1)
        self.assertIn("schema.missing_field", {item.code for item in report.errors})
        self.assertIn("schema.extra_field", {item.code for item in report.errors})

    def test_unknown_pydantic_schema_error_uses_safe_fallback(self) -> None:
        report = validate_module(
            {
                "module_id": 42,
                "version": "0.1.0",
                "world_ref": "coc-7e",
                "background": "测试背景。",
                "scenes": [],
                "entities": [],
                "checkpoints": [],
                "win_conditions": [],
            }
        )

        self.assertFalse(report.is_valid)
        self.assertEqual(report.errors[0].code, "schema.invalid")
        self.assertEqual(report.errors[0].path, "module_id")
        self.assertNotIn("string_type", report.errors[0].message)


if __name__ == "__main__":
    unittest.main()
