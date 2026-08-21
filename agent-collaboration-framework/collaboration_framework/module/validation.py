"""Shared result types for the deterministic validation boundary.

v1 的 `ModuleDraft -> ModuleContent` 校验链随契约一起删除了 (#384)；留在这里的
只有两个结果类型，`validation_v3.py` 用它们汇报 v3 的校验结论。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["error", "warning"]
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    status: Literal["pass", "needs_revision", "blocked"]
    errors: tuple[ValidationIssue, ...] = ()
    warnings: tuple[ValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return self.status == "pass"
