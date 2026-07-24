from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from collaboration_framework.contracts import ModuleContent
from collaboration_framework.module import ModuleImportError, import_module_file
from tests.check_candidate_snapshots import DEMO_CHECK_CANDIDATES


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"
INVALID = FIXTURES / "invalid-modules"


class ModuleImportWorkflowTests(unittest.TestCase):
    def test_valid_module_is_validated_and_published(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "published.json"

            result = import_module_file(
                FIXTURES / "demo-module.json",
                output_path,
                skill_catalog=DEMO_CHECK_CANDIDATES,
            )

            self.assertEqual(result.status, "published")
            self.assertEqual(result.validation_report.status, "pass")
            self.assertIsNotNone(result.publish_result)
            self.assertEqual(result.publish_result.output_path, output_path)
            loaded = ModuleContent.model_validate_json(
                output_path.read_text(encoding="utf-8")
            )
            self.assertEqual(loaded, result.validation_report.content)

    def test_same_input_produces_identical_published_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.json"
            second = Path(directory) / "second.json"

            import_module_file(
                FIXTURES / "demo-module.json",
                first,
                skill_catalog=DEMO_CHECK_CANDIDATES,
            )
            import_module_file(
                FIXTURES / "demo-module.json",
                second,
                skill_catalog=DEMO_CHECK_CANDIDATES,
            )

            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_invalid_json_returns_report_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "published.json"

            result = import_module_file(INVALID / "invalid-json.txt", output_path)

            self.assertEqual(result.status, "needs_revision")
            self.assertEqual(result.publish_result, None)
            self.assertEqual(result.validation_report.errors[0].code, "schema.invalid_json")
            self.assertFalse(output_path.exists())

    def test_missing_field_returns_report_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "published.json"

            result = import_module_file(INVALID / "missing-field.json", output_path)

            self.assertEqual(result.status, "needs_revision")
            self.assertIn(
                "schema.missing_field",
                {issue.code for issue in result.validation_report.errors},
            )
            self.assertFalse(output_path.exists())

    def test_semantic_errors_are_all_returned_without_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "published.json"

            result = import_module_file(
                INVALID / "multiple-semantic-errors.json",
                output_path,
                skill_catalog=DEMO_CHECK_CANDIDATES,
            )

            self.assertEqual(result.status, "needs_revision")
            self.assertGreaterEqual(len(result.validation_report.errors), 7)
            self.assertFalse(output_path.exists())

    def test_missing_input_has_stable_io_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            output_path = Path(directory) / "published.json"

            with self.assertRaises(ModuleImportError) as caught:
                import_module_file(missing, output_path)

            self.assertEqual(caught.exception.code, "import.input_not_found")
            self.assertEqual(caught.exception.path, missing)
            self.assertFalse(output_path.exists())

    def test_non_utf8_input_has_stable_io_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory) / "invalid-utf8.json"
            input_path.write_bytes(b"\xff\xfe")
            output_path = Path(directory) / "published.json"

            with self.assertRaises(ModuleImportError) as caught:
                import_module_file(input_path, output_path)

            self.assertEqual(caught.exception.code, "import.input_invalid_utf8")
            self.assertFalse(output_path.exists())

    def test_input_directory_has_stable_read_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            input_path = Path(directory)
            output_path = Path(directory) / "published.json"

            with self.assertRaises(ModuleImportError) as caught:
                import_module_file(input_path, output_path)

            self.assertEqual(caught.exception.code, "import.input_read_failed")
            self.assertFalse(output_path.exists())

    def test_unwritable_output_has_stable_write_error(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory)

            with self.assertRaises(ModuleImportError) as caught:
                import_module_file(FIXTURES / "demo-module.json", output_path)

            self.assertEqual(caught.exception.code, "import.output_write_failed")
            self.assertEqual(caught.exception.path, output_path)

    def test_paths_must_be_path_instances(self) -> None:
        with self.assertRaises(TypeError):
            import_module_file("input.json", Path("output.json"))  # type: ignore[arg-type]
        with self.assertRaises(TypeError):
            import_module_file(Path("input.json"), "output.json")  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
