"""Construct authoritative room state from one published ModuleContent."""

from __future__ import annotations

from collections.abc import Mapping

from collaboration_framework.contracts import (
    ItemCustody,
    ItemDisplay,
    ItemInstance,
    ItemKnowledge,
    ModuleContent,
    ModuleContentV3,
)

from .models import ActorState, GameState, WorldTimePoint, WorldTimeState


def create_initial_game_state(
    module_content: ModuleContent | ModuleContentV3,
    *,
    room_id: str,
    actors: Mapping[str, ActorState],
    world_time: WorldTimeState | None = None,
) -> GameState:
    """Hydrate the module-declared opening location and entity state defaults."""

    if isinstance(module_content, ModuleContentV3):
        initial = module_content.initial_state
        entities = {entity.id: dict(entity.state) for entity in module_content.entities}
        # `initial_state.entity_state` is an authored override on top of each
        # Entity's own defaults, so it is merged last.
        for entity_id, overrides in initial.entity_state.items():
            entities.setdefault(entity_id, {}).update(overrides)
        items = _initial_items(module_content, room_id)
        return GameState(
            room_id=room_id,
            scene_id=initial.start_location_id,
            actors=dict(actors),
            entities=entities,
            world_time=world_time or _world_time_for(module_content),
            discovered_facts=tuple(sorted(initial.revealed_information_ids)),
            item_instances=items,
            party_item_knowledge={
                item.id: ItemKnowledge(item_id=item.id, identity="known")
                for entity in module_content.entities
                if (item := items.get(entity.id)) is not None
                and entity.visibility in {"public", "party"}
            },
        )
    return GameState(
        room_id=room_id,
        scene_id=module_content.initial_scene_id,
        actors=dict(actors),
        entities={entity.id: dict(entity.state) for entity in module_content.entities},
        world_time=world_time or WorldTimeState(),
    )


def _world_time_for(module_content: ModuleContentV3) -> WorldTimeState:
    """Open the room on the module's declared starting time point (#245 §一.1).

    A module that declares none opens on its first ordered point rather than at
    an arbitrary hour: every later jump is resolved relative to `current_point_id`,
    so the room has to start *on* a point, not between them.
    """

    points = sorted(
        module_content.time_policy.default_points, key=lambda item: item.order
    )
    start_id = module_content.initial_state.start_time_point_id
    point = next((item for item in points if item.id == start_id), None) or points[0]
    return WorldTimeState(
        current=WorldTimePoint(day_index=0, hour_of_day=point.hour_of_day),
        current_point_id=point.id,
    )


def _initial_items(
    module_content: ModuleContentV3,
    room_id: str,
) -> dict[str, ItemInstance]:
    items: dict[str, ItemInstance] = {}
    for entity in module_content.entities:
        if entity.item_component is None:
            continue
        carried_by = next(
            (
                relation.target_id
                for relation in entity.relations
                if relation.kind == "carried_by"
            ),
            None,
        )
        custody = (
            ItemCustody(kind="actor_inventory", ref_id=carried_by, form="carried")
            if carried_by is not None
            else ItemCustody(
                kind="location",
                ref_id=entity.located_in
                or module_content.initial_state.start_location_id,
                form="placed",
            )
        )
        seed_event_id = f"module_seed:{entity.id}"
        items[entity.id] = ItemInstance(
            id=entity.id,
            room_id=room_id,
            origin="canon",
            definition_id=entity.id,
            display=ItemDisplay(
                name=entity.player_visible_name or entity.name,
                description=entity.description,
            ),
            item_component=entity.item_component,
            custody=custody,
            version=1,
            created_event_id=seed_event_id,
            last_event_id=seed_event_id,
            updated_revision="0",
        )
    return items
