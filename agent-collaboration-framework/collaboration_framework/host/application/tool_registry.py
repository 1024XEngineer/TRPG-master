"""Framework-independent registration and invocation for Host Agent tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from dataclasses import dataclass
import re
from types import MappingProxyType
from typing import Any, Literal, TypeAlias

from pydantic import ValidationError

from collaboration_framework.contracts import ContractModel
from collaboration_framework.host.schemas import (
    HostAgentContext,
    ToolErrorResult,
    make_tool_error,
)


ToolAccess: TypeAlias = Literal["read_only"]
ToolHandler: TypeAlias = Callable[
    [HostAgentContext, Any],
    Awaitable[Any],
]

_TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    """Trusted project-owned metadata and implementation for one tool."""

    name: str
    description: str
    args_model: type[ContractModel]
    result_model: type[ContractModel]
    public_progress_label: str
    handler: ToolHandler
    access: ToolAccess = "read_only"

    def __post_init__(self) -> None:
        if not _TOOL_NAME_PATTERN.fullmatch(self.name):
            raise ValueError(
                "tool name must start with a lowercase letter and contain "
                "only lowercase letters, digits, and underscores"
            )
        if not self.description.strip():
            raise ValueError("tool description must not be empty")
        if not self.public_progress_label.strip():
            raise ValueError("tool public progress label must not be empty")
        if self.access != "read_only":
            raise ValueError("Host Agent tools must be read_only")
        for field_name, model in (
            ("args_model", self.args_model),
            ("result_model", self.result_model),
        ):
            if not isinstance(model, type) or not issubclass(model, ContractModel):
                raise TypeError(f"{field_name} must be a ContractModel type")
        if not callable(self.handler):
            raise TypeError("tool handler must be callable")

    def arguments_json_schema(self) -> dict[str, object]:
        return self.args_model.model_json_schema(
            by_alias=True,
            mode="validation",
        )

    def result_json_schema(self) -> dict[str, object]:
        return self.result_model.model_json_schema(
            by_alias=True,
            mode="validation",
        )


class ToolRegistry:
    """Immutable registry of the only callables available to a Host Agent."""

    def __init__(self, definitions: Iterable[ToolDefinition]) -> None:
        registered: dict[str, ToolDefinition] = {}
        for definition in definitions:
            if definition.name in registered:
                raise ValueError(f"duplicate tool registration: {definition.name}")
            registered[definition.name] = definition
        self._definitions = MappingProxyType(registered)

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return tuple(
            self._definitions[name]
            for name in sorted(self._definitions)
        )

    def bind(self, context: HostAgentContext) -> BoundToolRegistry:
        if not isinstance(context, HostAgentContext):
            raise TypeError("context must be a HostAgentContext")
        return BoundToolRegistry(self, context)

    def _find(self, name: str) -> ToolDefinition | None:
        return self._definitions.get(name)


@dataclass(frozen=True, slots=True)
class BoundToolRegistry:
    """A registry view whose trusted player scope cannot be model-supplied."""

    registry: ToolRegistry
    context: HostAgentContext

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self.registry.definitions

    async def ainvoke(
        self,
        tool_name: str,
        arguments: object,
    ) -> ContractModel:
        if not isinstance(tool_name, str):
            return make_tool_error("TOOL_NOT_FOUND")
        definition = self.registry._find(tool_name)
        if definition is None:
            return make_tool_error("TOOL_NOT_FOUND")

        try:
            parsed_arguments = definition.args_model.model_validate(arguments)
        except (TypeError, ValueError, ValidationError):
            return make_tool_error("INVALID_TOOL_ARGUMENTS")

        try:
            raw_result = await definition.handler(self.context, parsed_arguments)
        except Exception:
            return make_tool_error("TOOL_INTERNAL_ERROR")

        if isinstance(raw_result, ToolErrorResult):
            return raw_result

        try:
            return definition.result_model.model_validate(raw_result)
        except (TypeError, ValueError, ValidationError):
            return make_tool_error("INVALID_TOOL_RESULT")
