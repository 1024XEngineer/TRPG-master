"""Public entry points for Member C's deterministic validation boundary."""

from .validation import ValidationIssue, ValidationReport
from .validation_v3 import validate_module_v3, validate_module_v3_json

__all__ = [
    "ValidationIssue",
    "ValidationReport",
    "validate_module_v3",
    "validate_module_v3_json",
]
