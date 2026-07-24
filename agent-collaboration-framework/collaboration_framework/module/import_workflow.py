"""Phase 1 application use case for importing one Module JSON file."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Collection, Literal

from .publish import PublishResult, publish_module
from .validation import ValidationReport, validate_module_json


class ModuleImportError(RuntimeError):
    """Stable file-system failure raised outside content validation."""

    def __init__(self, *, code: str, path: Path, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.path = path


@dataclass(frozen=True)
class ImportResult:
    """Result of composing file input, Validation, and optional Publish."""

    status: Literal["published", "needs_revision", "blocked"]
    validation_report: ValidationReport
    publish_result: PublishResult | None = None


def import_module_file(
    input_path: Path,
    output_path: Path,
    *,
    skill_catalog: Collection[str] | None = None,
) -> ImportResult:
    """Validate one UTF-8 JSON file and publish it only when it passes."""

    if not isinstance(input_path, Path):
        raise TypeError("input_path 必须是 pathlib.Path。")
    if not isinstance(output_path, Path):
        raise TypeError("output_path 必须是 pathlib.Path。")

    try:
        payload = input_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ModuleImportError(
            code="import.input_not_found",
            path=input_path,
            message="输入 Module JSON 文件不存在。",
        ) from error
    except UnicodeDecodeError as error:
        raise ModuleImportError(
            code="import.input_invalid_utf8",
            path=input_path,
            message="输入 Module JSON 文件不是合法 UTF-8。",
        ) from error
    except OSError as error:
        raise ModuleImportError(
            code="import.input_read_failed",
            path=input_path,
            message="无法读取输入 Module JSON 文件。",
        ) from error

    report = validate_module_json(payload, skill_catalog=skill_catalog)
    if report.status != "pass":
        return ImportResult(
            status=report.status,
            validation_report=report,
        )

    try:
        published = publish_module(report, output_path)
    except OSError as error:
        raise ModuleImportError(
            code="import.output_write_failed",
            path=output_path,
            message="无法写入发布 Module JSON 文件。",
        ) from error
    return ImportResult(
        status="published",
        validation_report=report,
        publish_result=published,
    )
