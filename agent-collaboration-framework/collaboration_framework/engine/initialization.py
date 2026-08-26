"""Construct authoritative room state from one published ModuleContent."""

from __future__ import annotations

from collections.abc import Mapping

from collaboration_framework.contracts import (
    ItemAcquisition,
    ItemComponent,
    ItemCustody,
    ItemDisplay,
    ItemInstance,
    ItemKnowledge,
    ModuleContentV3,
)

from .models import ActorState, GameState, WorldTimePoint, WorldTimeState


def create_initial_game_state(
    module_content: ModuleContentV3,
    *,
    room_id: str,
    actors: Mapping[str, ActorState],
    world_time: WorldTimeState | None = None,
) -> GameState:
    """Hydrate the module-declared opening location and entity state defaults."""

    initial = module_content.initial_state
    entities = {entity.id: dict(entity.state) for entity in module_content.entities}
    # `initial_state.entity_state` is an authored override on top of each
    # Entity's own defaults, so it is merged last.
    for entity_id, overrides in initial.entity_state.items():
        entities.setdefault(entity_id, {}).update(overrides)
    items = _initial_items(module_content, room_id)
    carried, carried_knowledge = _initial_carried_equipment(actors, room_id)
    items.update(carried)
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
        actor_item_knowledge=carried_knowledge,
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
        current_time_segment=point.resolved_segment,
    )


def _initial_carried_equipment(
    actors: Mapping[str, ActorState],
    room_id: str,
) -> tuple[dict[str, ItemInstance], dict[str, dict[str, ItemKnowledge]]]:
    """Turn each investigator's declared kit into real carried ItemInstances.

    The character sheet lists equipment as free text, and until it exists as
    ItemInstances the Engine simply does not know the investigator owns
    anything: the backpack reads empty, and the first time a rope or a lantern
    matters it has to be conjured mid-scene. Seeding it at room start is what
    keeps the kit from behaving like a bottomless bag.

    This is deliberately *not* the InventoryImportDraft review flow (#212) —
    nothing is vetted, normalised or rejected here. Declared gear is taken at
    face value as ordinary runtime items so that play stays consistent; the
    review workflow can replace this later without changing the shape.
    """

    items: dict[str, ItemInstance] = {}
    knowledge: dict[str, dict[str, ItemKnowledge]] = {}
    for actor_id, actor in actors.items():
        declared = actor.state.get("equipment")
        if not isinstance(declared, (list, tuple)):
            continue
        seen: set[str] = set()
        for index, raw in enumerate(declared):
            if not isinstance(raw, str):
                continue
            name = raw.strip()
            if not name or name in seen:
                continue
            seen.add(name)
            item_id = f"{actor_id}:equipment:{index}"[:100]
            seed_event_id = f"character_equipment_seed:{item_id}"
            items[item_id] = ItemInstance(
                id=item_id,
                room_id=room_id,
                origin="runtime",
                definition_id=item_id,
                display=ItemDisplay(name=name[:200]),
                item_component=ItemComponent(),
                custody=ItemCustody(
                    kind="actor_inventory", ref_id=actor_id, form="carried"
                ),
                acquisition=ItemAcquisition(
                    source_type="character_import",
                    source_id=actor.source_character_id,
                    player_safe_label="随身携带",
                    event_id=seed_event_id,
                    revision="0",
                ),
                created_event_id=seed_event_id,
                last_event_id=seed_event_id,
                updated_revision="0",
            )
            # 自己的装备只有自己认得，和已有的 held item 投影口径一致。
            knowledge.setdefault(actor_id, {})[item_id] = ItemKnowledge(
                item_id=item_id, scope="actor", identity="known"
            )
    return items, knowledge


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
