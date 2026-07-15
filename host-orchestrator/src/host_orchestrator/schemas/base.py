from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict

SchemaVersion: TypeAlias = Literal["1"]
JsonValue: TypeAlias = (
    str | int | float | bool | None | list["JsonValue"] | dict[str, "JsonValue"]
)
JsonObject: TypeAlias = dict[str, JsonValue]


class ContractModel(BaseModel):
    """Strict immutable base for orchestration boundary contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True)
