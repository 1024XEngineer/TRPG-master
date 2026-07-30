"""Base types shared by stable cross-component contracts."""

from __future__ import annotations

import json
from typing import Any, TypeAlias

from pydantic import BaseModel, ConfigDict

JsonObject: TypeAlias = dict[str, Any]


class ContractError(ValueError):
    """Raised when a deterministic boundary invariant is violated."""


class ContractModel(BaseModel):
    """Strict immutable base model for public contracts."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    def to_json_dict(self) -> JsonObject:
        return json.loads(self.model_dump_json(by_alias=True))
