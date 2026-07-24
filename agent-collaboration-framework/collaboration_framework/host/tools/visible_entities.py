"""Read-only tools over the PlayerView already bound to a Host Agent run."""

from __future__ import annotations

import unicodedata

from collaboration_framework.host.application.tool_registry import ToolDefinition
from collaboration_framework.host.schemas import (
    GetVisibleEntityArgs,
    GetVisibleEntityResult,
    HostAgentContext,
    SearchVisibleEntitiesArgs,
    SearchVisibleEntitiesResult,
    ToolErrorResult,
    VisibleEntitySummary,
    make_tool_error,
)


def normalize_search_text(value: str) -> str:
    """Normalize text deterministically without fuzzy or semantic matching."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


async def search_visible_entities(
    context: HostAgentContext,
    arguments: SearchVisibleEntitiesArgs,
) -> SearchVisibleEntitiesResult:
    query = normalize_search_text(arguments.query)
    ranked: list[tuple[int, str, VisibleEntitySummary]] = []

    for entity in context.player_view.visible_entities:
        if arguments.kind is not None and entity.kind != arguments.kind:
            continue

        normalized_name = normalize_search_text(entity.name)
        normalized_aliases = tuple(
            normalize_search_text(alias) for alias in entity.aliases
        )
        normalized_content = normalize_search_text(entity.content)

        if query in normalized_name:
            rank = 0
        elif any(query in alias for alias in normalized_aliases):
            rank = 1
        elif query in normalized_content:
            rank = 2
        else:
            continue

        ranked.append(
            (
                rank,
                entity.id,
                VisibleEntitySummary(
                    id=entity.id,
                    kind=entity.kind,
                    name=entity.name,
                ),
            )
        )

    ranked.sort(key=lambda item: (item[0], item[1]))
    return SearchVisibleEntitiesResult(
        matches=tuple(item[2] for item in ranked[: arguments.limit])
    )


async def get_visible_entity(
    context: HostAgentContext,
    arguments: GetVisibleEntityArgs,
) -> GetVisibleEntityResult | ToolErrorResult:
    entity = next(
        (
            visible_entity
            for visible_entity in context.player_view.visible_entities
            if visible_entity.id == arguments.entity_id
        ),
        None,
    )
    if entity is None:
        return make_tool_error("ENTITY_NOT_VISIBLE")

    checkpoint_options = tuple(
        sorted(
            (
                option
                for option in context.player_view.checkpoint_options
                if option.target_id == entity.id
            ),
            key=lambda option: option.id,
        )
    )
    return GetVisibleEntityResult(
        id=entity.id,
        kind=entity.kind,
        name=entity.name,
        aliases=entity.aliases,
        content=entity.content,
        checkpoint_options=checkpoint_options,
    )


SEARCH_VISIBLE_ENTITIES_TOOL = ToolDefinition(
    name="search_visible_entities",
    description=(
        "Search the entities visible in the current player view by name, "
        "alias, or player-safe description."
    ),
    args_model=SearchVisibleEntitiesArgs,
    result_model=SearchVisibleEntitiesResult,
    public_progress_label="正在查找当前场景中的可见实体",
    handler=search_visible_entities,
)

GET_VISIBLE_ENTITY_TOOL = ToolDefinition(
    name="get_visible_entity",
    description=(
        "Read player-safe details and current checkpoint options for one "
        "entity returned by search_visible_entities."
    ),
    args_model=GetVisibleEntityArgs,
    result_model=GetVisibleEntityResult,
    public_progress_label="正在读取可见实体信息",
    handler=get_visible_entity,
)
