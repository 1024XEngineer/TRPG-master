"""C-owned deterministic module-publication boundary."""

from __future__ import annotations

from typing import Any

from collaboration_framework.contracts import ModuleContent


def validate_module(payload: ModuleContent | dict[str, Any]) -> ModuleContent:
    """Validate shape and shared publication invariants without runtime effects."""

    return ModuleContent.model_validate(payload)


def validate_module_json(payload: str | bytes) -> ModuleContent:
    return ModuleContent.model_validate_json(payload)
