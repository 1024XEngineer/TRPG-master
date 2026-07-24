from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from pydantic import ValidationError

from collaboration_framework.contracts import ModuleContent


ROOT = Path(__file__).resolve().parents[1]
DEMO_MODULE = ROOT / "fixtures" / "demo-module.json"


def demo_payload() -> dict:
    return json.loads(DEMO_MODULE.read_text(encoding="utf-8"))


class ModuleContentContractSmokeTests(unittest.TestCase):
    def test_demo_fixture_constructs_the_published_contract(self) -> None:
        content = ModuleContent.model_validate_json(
            DEMO_MODULE.read_text(encoding="utf-8")
        )

        self.assertEqual(content.module_id, "study-demo")
        self.assertIsInstance(content.scenes, tuple)
        self.assertIsInstance(content.entities, tuple)
        self.assertIsInstance(content.checkpoints, tuple)
        self.assertIsInstance(content.win_conditions, tuple)
        self.assertEqual(len(content.scenes), 1)
        self.assertEqual(len(content.entities), 5)
        self.assertEqual(len(content.checkpoints), 2)
        self.assertEqual(len(content.win_conditions), 2)

    def test_undefined_field_is_rejected(self) -> None:
        payload = demo_payload()
        payload["schema_version"] = "1.0"

        with self.assertRaises(ValidationError) as raised:
            ModuleContent.model_validate(payload)

        self.assertIn(
            "extra_forbidden",
            {item["type"] for item in raised.exception.errors()},
        )

    def test_missing_required_field_is_rejected(self) -> None:
        payload = demo_payload()
        payload.pop("world_ref")

        with self.assertRaises(ValidationError) as raised:
            ModuleContent.model_validate(payload)

        self.assertIn("missing", {item["type"] for item in raised.exception.errors()})

    def test_invalid_enum_value_is_rejected(self) -> None:
        payload = copy.deepcopy(demo_payload())
        payload["entities"][0]["kind"] = "monster"

        with self.assertRaises(ValidationError) as raised:
            ModuleContent.model_validate(payload)

        self.assertIn(
            "literal_error",
            {item["type"] for item in raised.exception.errors()},
        )

    def test_published_contract_is_frozen(self) -> None:
        content = ModuleContent.model_validate(demo_payload())

        with self.assertRaises(ValidationError) as raised:
            content.module_id = "changed"

        self.assertIn(
            "frozen_instance",
            {item["type"] for item in raised.exception.errors()},
        )


if __name__ == "__main__":
    unittest.main()
