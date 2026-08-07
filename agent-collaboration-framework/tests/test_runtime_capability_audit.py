"""Load-time refusal of modules the deterministic runtime cannot honour.

Rescued from `test_rule_engine_core.py`, which was deleted with the Checkpoint
kernel (#226). The audit itself is *not* v2: `room.py` calls
`require_runtime_capabilities` when a room is created, so an unsupported
`world_ref` or an unsafe expression is still rejected before anyone can play.
Deleting the kernel's test file wholesale would have left that gate uncovered.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from collaboration_framework.contracts import (
    ConditionSpec,
    ContractError,
    ModuleContent,
)
from collaboration_framework.engine import (
    audit_runtime_capabilities,
    require_runtime_capabilities,
)

ROOT = Path(__file__).resolve().parents[1]


def load_paper_chase() -> ModuleContent:
    examples = ROOT / "docs" / "module-parser" / "examples" / "module-content-validation"
    for path in examples.rglob("module-content-draft.json"):
        payload = path.read_text(encoding="utf-8")
        if '"module_id": "paper-chase-zh-coc7"' in payload:
            return ModuleContent.model_validate_json(payload)
    raise AssertionError("Paper Chase ModuleContent fixture was not found")


class RuntimeCapabilityAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_paper_chase()

    def test_paper_chase_passes_runtime_capability_audit(self) -> None:
        self.assertEqual(audit_runtime_capabilities(self.module), ())

    def test_capability_audit_rejects_unsafe_expression_before_runtime(self) -> None:
        original = self.module.module_rules[0]
        unsafe_rule = original.model_copy(
            update={"when": ConditionSpec(expr="keeper.read_secret()")}
        )
        unsafe_module = self.module.model_copy(
            update={
                "module_rules": (
                    unsafe_rule,
                    *self.module.module_rules[1:],
                )
            }
        )

        issues = audit_runtime_capabilities(unsafe_module)

        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].owner, f"rule:{original.id}")
        self.assertIn("expression:", issues[0].capability)
        with self.assertRaises(ContractError):
            require_runtime_capabilities(unsafe_module)


if __name__ == "__main__":
    unittest.main()
