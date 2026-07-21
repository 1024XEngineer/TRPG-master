from __future__ import annotations

import importlib.util
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PATH = REPOSITORY_ROOT / "docs/module-parser/paper-chase/module-package.json"
VALIDATOR_PATH = REPOSITORY_ROOT / "trpg-backend/scripts/validate_module_package.py"

SPEC = importlib.util.spec_from_file_location("validate_module_package", VALIDATOR_PATH)
assert SPEC and SPEC.loader
VALIDATOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VALIDATOR)


@pytest.fixture
def package() -> dict[str, Any]:
    return json.loads(PACKAGE_PATH.read_text(encoding="utf-8"))


def test_paper_chase_package_is_valid(package: dict[str, Any]) -> None:
    assert VALIDATOR.validate(package) == []


def test_missing_location_reference_is_rejected(package: dict[str, Any]) -> None:
    invalid = deepcopy(package)
    invalid["content"]["scenes"][0]["location_ids"] = ["location.missing"]

    errors = VALIDATOR.validate(invalid)

    assert any("references missing location.missing" in error for error in errors)


def test_hidden_route_requires_discovery_rule(package: dict[str, Any]) -> None:
    invalid = deepcopy(package)
    hidden_route = invalid["content"]["locations"][2]["connections"][1]
    hidden_route.pop("discovery_clue_id")

    errors = VALIDATOR.validate(invalid)

    assert any("hidden route requires" in error for error in errors)


def test_map_requires_location_binding(package: dict[str, Any]) -> None:
    invalid = deepcopy(package)
    invalid["assets"][1]["linked_location_ids"] = []

    errors = VALIDATOR.validate(invalid)

    assert any("map must have linked_location_ids" in error for error in errors)


def test_source_segments_are_required(package: dict[str, Any]) -> None:
    invalid = deepcopy(package)
    invalid["source_manifest"]["segments"] = []

    errors = VALIDATOR.validate(invalid)

    assert "source_manifest.segments must be a non-empty array" in errors
