"""Bridge project-owned tools into OpenAI Agents SDK function tools."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any

from agents import FunctionTool
from agents.exceptions import AgentsException

from collaboration_framework.host.application.tool_registry import (
    BoundToolRegistry,
)
from collaboration_framework.host.schemas import make_tool_error


class ToolBudgetExceeded(AgentsException):
    """Internal sentinel used to stop the SDK loop without provider text."""


@dataclass(slots=True)
class ToolRunState:
    """The single budget and timeout authority for one Host Agent run."""

    bound_registry: BoundToolRegistry
    max_tool_calls: int
    tool_timeout_seconds: float
    tool_calls: int = 0
    registry_invocations: int = 0

    async def invoke(self, tool_name: str, raw_arguments: str) -> str:
        self.tool_calls += 1
        if self.tool_calls > self.max_tool_calls:
            raise ToolBudgetExceeded("Host Agent tool budget exceeded")

        arguments = _decode_arguments(raw_arguments)
        if arguments is None:
            result = make_tool_error("INVALID_TOOL_ARGUMENTS")
        else:
            self.registry_invocations += 1
            try:
                async with asyncio.timeout(self.tool_timeout_seconds):
                    result = await self.bound_registry.ainvoke(
                        tool_name,
                        arguments,
                    )
            except TimeoutError:
                result = make_tool_error("TOOL_TIMEOUT")

        return result.model_dump_json(by_alias=True)


def build_sdk_tools(state: ToolRunState) -> list[FunctionTool]:
    """Create per-run SDK tools whose scope is already bound and immutable."""

    tools: list[FunctionTool] = []
    for definition in state.bound_registry.definitions:
        tool_name = definition.name

        async def invoke_tool(
            _context: Any,
            raw_arguments: str,
            *,
            _tool_name: str = tool_name,
        ) -> str:
            return await state.invoke(_tool_name, raw_arguments)

        tools.append(
            FunctionTool(
                name=definition.name,
                description=definition.description,
                params_json_schema=definition.arguments_json_schema(),
                on_invoke_tool=invoke_tool,
                strict_json_schema=True,
            )
        )
    return tools


def _decode_arguments(raw_arguments: str) -> dict[str, object] | None:
    try:
        decoded = json.loads(raw_arguments or "{}")
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    if not isinstance(decoded, dict):
        return None
    return decoded
