"""Framework-independent schemas for player-safe Host Agent tools."""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import Field

from collaboration_framework.contracts import CheckpointOption, ContractModel


ToolErrorCode: TypeAlias = Literal[
    "TOOL_NOT_FOUND",
    "INVALID_TOOL_ARGUMENTS",
    "ENTITY_NOT_VISIBLE",
    "INVALID_TOOL_RESULT",
    "TOOL_INTERNAL_ERROR",
    "TOOL_TIMEOUT",
]


class SearchVisibleEntitiesArgs(ContractModel):
    query: str = Field(min_length=1, max_length=200)
    kind: Literal["npc", "object", "location"] | None = None
    limit: int = Field(default=5, ge=1, le=5)


class VisibleEntitySummary(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    name: str = Field(min_length=1)


class SearchVisibleEntitiesResult(ContractModel):
    matches: tuple[VisibleEntitySummary, ...] = ()


class GetVisibleEntityArgs(ContractModel):
    entity_id: str = Field(min_length=1)


class GetVisibleEntityResult(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    content: str
    checkpoint_options: tuple[CheckpointOption, ...] = ()


class ToolError(ContractModel):
    code: ToolErrorCode
    message: str = Field(min_length=1)


class ToolErrorResult(ContractModel):
    error: ToolError


_ERROR_MESSAGES: dict[ToolErrorCode, str] = {
    "TOOL_NOT_FOUND": "The requested tool is not available.",
    "INVALID_TOOL_ARGUMENTS": "The tool arguments are invalid.",
    "ENTITY_NOT_VISIBLE": (
        "The requested entity is not available in the current player view."
    ),
    "INVALID_TOOL_RESULT": "The tool returned an invalid result.",
    "TOOL_INTERNAL_ERROR": "The tool could not complete the request.",
    "TOOL_TIMEOUT": "The tool timed out before completing the request.",
}


def make_tool_error(code: ToolErrorCode) -> ToolErrorResult:
    """Build a stable error without accepting provider or exception text."""

    return ToolErrorResult(
        error=ToolError(
            code=code,
            message=_ERROR_MESSAGES[code],
        )
    )
