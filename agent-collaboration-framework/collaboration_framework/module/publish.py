"""Phase 1 filesystem publication for validated module content only."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from collaboration_framework.contracts import ModuleContent

from .validation import ValidationReport


class PublishError(ValueError):
    """Raised when an input is not eligible for Phase 1 publication."""


@dataclass(frozen=True)
class PublishResult:
    """Receipt for one normalized ModuleContent JSON file."""

    output_path: Path
    bytes_written: int


def publish_module(
    report: ValidationReport,
    output_path: Path,
) -> PublishResult:
    """Write a passing report's ModuleContent as deterministic UTF-8 JSON.

    Publication deliberately accepts the Validation boundary output rather
    than raw data, a Parser Draft, or ModuleContent directly.
    """

    if not isinstance(report, ValidationReport):
        raise TypeError("publish_module 只接受 ValidationReport。")
    if report.status != "pass":
        raise PublishError("只有 status=pass 的 ValidationReport 才能发布。")
    if not isinstance(report.content, ModuleContent):
        raise PublishError("通过的 ValidationReport 必须包含 ModuleContent。")
    if not isinstance(output_path, Path):
        raise TypeError("output_path 必须是 pathlib.Path。")

    normalized = json.dumps(
        report.content.model_dump(mode="json", by_alias=True),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    output_path.write_text(normalized, encoding="utf-8")
    return PublishResult(
        output_path=output_path,
        bytes_written=len(normalized.encode("utf-8")),
    )
