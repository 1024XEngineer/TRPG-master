"""Publish-time predicate-name validation (issue #347 Phase 1).

`module/validation_v3.py::_condition_issues` now rejects a `PredicateCondition`
whose name is not in `engine/registry/predicates.py` — the one deliberate,
called-out behaviour change in issue #347's otherwise pure-refactor scope
(previously such a rule passed publish and simply never fired at runtime).
"""

from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import ModuleContentV3
from collaboration_framework.contracts.module_v3 import (
    AllCondition,
    NotCondition,
    PredicateCondition,
)
from collaboration_framework.module.validation_v3 import (
    _condition_issues,
    validate_module_v3,
)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = (
    ROOT
    / "docs"
    / "module-parser"
    / "examples"
    / "module-content-validation"
)


class ConditionIssuesTests(unittest.TestCase):
    def test_registered_predicate_name_has_no_issue(self) -> None:
        condition = PredicateCondition(predicate="entity_state_is", args={})
        self.assertEqual(_condition_issues(condition, "path"), [])

    def test_unknown_predicate_name_is_rejected(self) -> None:
        condition = PredicateCondition(predicate="made_up_predicate", args={})
        issues = _condition_issues(condition, "rules.0.trigger.when")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, "MODULE_V3_PREDICATE_UNKNOWN")
        self.assertEqual(issues[0].path, "rules.0.trigger.when.predicate")

    def test_empty_predicate_name_still_rejected_with_its_own_code(self) -> None:
        # The empty-name check must keep winning over the unknown-name check —
        # a blank string is not itself a registered name, but the more
        # specific/pre-existing MODULE_V3_PREDICATE_EMPTY code is more useful.
        # `model_construct` bypasses the pydantic field validator (min_length=1
        # after whitespace stripping) so this shape can be exercised directly,
        # same as `_condition_issues` already had to defend against it.
        condition = PredicateCondition.model_construct(
            op="predicate", predicate=" ", args={}
        )
        issues = _condition_issues(condition, "path")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, "MODULE_V3_PREDICATE_EMPTY")

    def test_unknown_predicate_nested_in_logical_combinators_is_found(self) -> None:
        condition = NotCondition(
            item=AllCondition(
                items=(
                    PredicateCondition(predicate="core_resolved", args={}),
                    PredicateCondition(predicate="made_up_predicate", args={}),
                )
            )
        )
        issues = _condition_issues(condition, "path")
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].code, "MODULE_V3_PREDICATE_UNKNOWN")
        self.assertEqual(issues[0].path, "path.item.items.1.predicate")


class RealFixturesStillPublishTests(unittest.TestCase):
    """The predicate names real, already-shipping modules use must all be
    registered — otherwise this phase would break existing content on the day
    it lands. This is the "grep every fixture before landing" check from the
    implementation plan, pinned as a regression test.
    """

    def test_known_v3_fixtures_pass_validation_unchanged(self) -> None:
        fixture_dirs = [p for p in FIXTURES.iterdir() if p.is_dir()]
        self.assertTrue(fixture_dirs, "expected at least one v3 fixture module")
        for directory in fixture_dirs:
            content_path = directory / "module-content-v3.json"
            if not content_path.exists():
                continue
            with self.subTest(module=directory.name):
                content = ModuleContentV3.model_validate_json(
                    content_path.read_text(encoding="utf-8")
                )
                report = validate_module_v3(content)
                predicate_issues = [
                    issue
                    for issue in report.errors
                    if issue.code
                    in ("MODULE_V3_PREDICATE_UNKNOWN", "MODULE_V3_PREDICATE_EMPTY")
                ]
                self.assertEqual(predicate_issues, [])


if __name__ == "__main__":
    unittest.main()
