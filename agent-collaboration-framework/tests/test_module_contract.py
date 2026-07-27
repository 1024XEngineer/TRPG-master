from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    AddOperationSpec,
    ConditionSpec,
    ModuleContent,
    VisibleInformation,
)
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
DEMO_MODULE = ROOT / "fixtures" / "demo-module.json"
CATALOG_MODULE = ROOT / "fixtures" / "module-content-v1-catalog.json"


def demo_payload() -> dict:
    return json.loads(DEMO_MODULE.read_text(encoding="utf-8"))


class ModuleContentContractSmokeTests(unittest.TestCase):
    def test_demo_fixture_constructs_the_published_contract(self) -> None:
        content = ModuleContent.model_validate_json(
            DEMO_MODULE.read_text(encoding="utf-8")
        )

        self.assertEqual(content.module_id, "study-demo")
        self.assertEqual(
            content.background,
            "当代书房调查演示；叙事保持克制、清晰，并只描述已确认的玩家可见事实。",
        )
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
        for field_name in ("world_ref", "background"):
            with self.subTest(field_name=field_name):
                payload = demo_payload()
                payload.pop(field_name)

                with self.assertRaises(ValidationError) as raised:
                    ModuleContent.model_validate(payload)

                self.assertIn(
                    "missing",
                    {item["type"] for item in raised.exception.errors()},
                )

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

    def test_full_parser_catalog_fixture_constructs_contract(self) -> None:
        content = ModuleContent.model_validate_json(
            CATALOG_MODULE.read_text(encoding="utf-8")
        )

        self.assertEqual(len(content.module_rules), 1)
        self.assertEqual(len(content.information_items), 1)
        self.assertIsNone(content.checkpoints[0].difficulty)
        self.assertTrue(content.checkpoints[0].visibility.requires_discovery)
        self.assertIsInstance(
            content.module_rules[0].then[0],
            AddOperationSpec,
        )
        self.assertIsInstance(
            content.entities[0].rules[0].player_visible_information[0],
            VisibleInformation,
        )
        self.assertFalse(content.win_conditions[0].is_ending)

    def test_expr_condition_round_trips_through_contract_dump(self) -> None:
        content = ModuleContent.model_validate_json(
            CATALOG_MODULE.read_text(encoding="utf-8")
        )

        dumped = content.model_dump(mode="json")
        loaded = ModuleContent.model_validate(dumped)

        self.assertEqual(loaded, content)
        self.assertEqual(
            dumped["module_rules"][0]["when"],
            {"expr": "clock.time_of_day == 'midnight'"},
        )

    def test_condition_requires_exactly_one_supported_form(self) -> None:
        self.assertIsNone(
            ConditionSpec.model_validate(
                {"path": "entity.x.state.value", "equals": None}
            ).equals
        )
        self.assertEqual(
            ConditionSpec.model_validate({"expr": "self.value > 0"}).expr,
            "self.value > 0",
        )
        invalid_conditions = (
            {},
            {"path": "entity.x.state.value"},
            {"equals": True},
            {
                "path": "entity.x.state.value",
                "equals": True,
                "expr": "self.value > 0",
            },
        )
        for payload in invalid_conditions:
            with (
                self.subTest(payload=payload),
                self.assertRaises(ValidationError),
            ):
                ConditionSpec.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
