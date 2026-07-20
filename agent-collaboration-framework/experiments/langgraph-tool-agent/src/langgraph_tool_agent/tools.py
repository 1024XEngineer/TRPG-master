"""Generic tools declared with LangChain's tool decorator."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain.tools import tool


@tool
def add_numbers(a: float, b: float) -> dict[str, float]:
    """Add two numbers; use this instead of doing arithmetic mentally."""
    if isinstance(a, bool) or isinstance(b, bool):
        raise ValueError("a and b must be numbers, not booleans")
    return {"sum": float(a) + float(b)}


@tool
def get_current_time(timezone_name: str) -> dict[str, str]:
    """Get the current time in an IANA timezone such as Asia/Shanghai."""
    try:
        timezone = ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"Unknown IANA timezone: {timezone_name}") from exc
    return {
        "timezone": timezone_name,
        "iso_time": datetime.now(timezone).isoformat(timespec="seconds"),
    }


TOOLS = [add_numbers, get_current_time]
