"""Public entry points for Member C's deterministic validation boundary.

Parser-internal intermediate representations are intentionally not re-exported
from this package. Shared consumers must use contracts.ModuleContent.
"""

from .import_workflow import ImportResult, ModuleImportError, import_module_file
from .publish import PublishError, PublishResult, publish_module
from .validation import (
    ValidationIssue,
    ValidationReport,
    validate_draft,
    validate_module,
    validate_module_json,
)

__all__ = [
    "ValidationIssue",
    "ValidationReport",
    "PublishError",
    "PublishResult",
    "ImportResult",
    "ModuleImportError",
    "import_module_file",
    "publish_module",
    "validate_draft",
    "validate_module",
    "validate_module_json",
]
