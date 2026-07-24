from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from collaboration_framework.contracts import ModuleContent
from collaboration_framework.module import (
    PublishError,
    ValidationReport,
    publish_module,
    validate_module_json,
)
from collaboration_framework.module.models import ModuleDraft


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "fixtures"


class ModulePublishTests(unittest.TestCase):
    def passing_report(self) -> ValidationReport:
        return validate_module_json((FIXTURES / "demo-module.json").read_text())

    def test_passing_report_publishes_normalized_module_json(self) -> None:
        report = self.passing_report()
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "module.json"

            result = publish_module(report, output_path)

            rendered = output_path.read_text(encoding="utf-8")
            loaded = ModuleContent.model_validate_json(rendered)
            self.assertEqual(loaded, report.content)
            self.assertEqual(result.output_path, output_path)
            self.assertEqual(result.bytes_written, len(rendered.encode("utf-8")))
            self.assertEqual(rendered, rendered.strip() + "\n")
            self.assertEqual(json.loads(rendered), report.content.to_json_dict())

    def test_publication_is_deterministic(self) -> None:
        report = self.passing_report()
        with tempfile.TemporaryDirectory() as directory:
            first = Path(directory) / "first.json"
            second = Path(directory) / "second.json"

            publish_module(report, first)
            publish_module(report, second)

            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_non_passing_report_is_rejected_without_writing(self) -> None:
        report = validate_module_json("not json")
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "module.json"

            with self.assertRaises(PublishError):
                publish_module(report, output_path)

            self.assertFalse(output_path.exists())

    def test_passing_report_without_content_is_rejected(self) -> None:
        report = ValidationReport(status="pass")
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "module.json"

            with self.assertRaises(PublishError):
                publish_module(report, output_path)

            self.assertFalse(output_path.exists())

    def test_passing_report_with_draft_content_is_rejected(self) -> None:
        draft = ModuleDraft.model_validate_json(
            (FIXTURES / "demo-module.json").read_text()
        )
        report = ValidationReport(status="pass", content=draft)  # type: ignore[arg-type]
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "module.json"

            with self.assertRaises(PublishError):
                publish_module(report, output_path)

            self.assertFalse(output_path.exists())

    def test_raw_dict_draft_and_module_content_are_rejected(self) -> None:
        report = self.passing_report()
        draft = ModuleDraft.model_validate_json(
            (FIXTURES / "demo-module.json").read_text()
        )
        invalid_inputs = ({}, draft, report.content)
        with tempfile.TemporaryDirectory() as directory:
            for index, value in enumerate(invalid_inputs):
                output_path = Path(directory) / f"module-{index}.json"
                with self.subTest(value=type(value).__name__):
                    with self.assertRaises(TypeError):
                        publish_module(value, output_path)  # type: ignore[arg-type]
                    self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
