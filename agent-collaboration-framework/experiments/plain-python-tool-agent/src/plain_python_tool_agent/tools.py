"""Generic tools and OpenAI-compatible schemas for the teaching example."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


ToolHandler = Callable[..., dict[str, Any]]


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: ToolHandler

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def add_numbers(a: float, b: float) -> dict[str, float]:
    """Return the sum of two numbers."""
    if isinstance(a, bool) or isinstance(b, bool):
        raise ValueError("a and b must be numbers, not booleans")
    return {"sum": float(a) + float(b)}


def get_current_time(timezone_name: str) -> dict[str, str]:
    """Return the current ISO-8601 time in an IANA timezone."""
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {timezone_name}") from exc
    return {
        "timezone": timezone_name,
        "iso_time": datetime.now(timezone).isoformat(timespec="seconds"),
    }


TOOLS = (
    ToolDefinition(
        name="add_numbers",
        description="Add two numbers. Use this instead of doing arithmetic mentally.",
        parameters={
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "The first number."},
                "b": {"type": "number", "description": "The second number."},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        },
        handler=add_numbers,
    ),
    ToolDefinition(
        name="get_current_time",
        description="Get the current time in an IANA timezone such as Asia/Shanghai.",
        parameters={
            "type": "object",
            "properties": {
                "timezone_name": {
                    "type": "string",
                    "description": "An IANA timezone name, for example Europe/Paris.",
                }
            },
            "required": ["timezone_name"],
            "additionalProperties": False,
        },
        handler=get_current_time,
    ),
)

TOOL_REGISTRY = {tool.name: tool for tool in TOOLS}
OPENAI_TOOLS = [tool.as_openai_tool() for tool in TOOLS]
