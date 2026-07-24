"""Player-safe Host Agent tool definitions."""

from collaboration_framework.host.application.tool_registry import ToolRegistry

from .visible_entities import (
    GET_VISIBLE_ENTITY_TOOL,
    SEARCH_VISIBLE_ENTITIES_TOOL,
    get_visible_entity,
    normalize_search_text,
    search_visible_entities,
)


def build_player_view_tool_registry() -> ToolRegistry:
    """Build the immutable first-party read-only tool set."""

    return ToolRegistry(
        (
            SEARCH_VISIBLE_ENTITIES_TOOL,
            GET_VISIBLE_ENTITY_TOOL,
        )
    )


__all__ = [
    "GET_VISIBLE_ENTITY_TOOL",
    "SEARCH_VISIBLE_ENTITIES_TOOL",
    "build_player_view_tool_registry",
    "get_visible_entity",
    "normalize_search_text",
    "search_visible_entities",
]
