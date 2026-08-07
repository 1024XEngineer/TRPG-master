"""Construct authoritative room state from one published ModuleContent."""

from __future__ import annotations

from collections.abc import Mapping

from collaboration_framework.contracts import ModuleContent, ModuleContentV3

from .models import ActorState, ClockState, GameState, time_of_day_at


def create_initial_game_state(
    module_content: ModuleContent | ModuleContentV3,
    *,
    room_id: str,
    actors: Mapping[str, ActorState],
    clock: ClockState | None = None,
) -> GameState:
    """Hydrate the module-declared opening location and entity state defaults."""

    if isinstance(module_content, ModuleContentV3):
        initial = module_content.initial_state
        entities = {
            entity.id: dict(entity.state) for entity in module_content.entities
        }
        # `initial_state.entity_state` is an authored override on top of each
        # Entity's own defaults, so it is merged last.
        for entity_id, overrides in initial.entity_state.items():
            entities.setdefault(entity_id, {}).update(overrides)
        return GameState(
            room_id=room_id,
            scene_id=initial.start_location_id,
            actors=dict(actors),
            entities=entities,
            clock=clock or _clock_for(module_content),
            discovered_facts=tuple(sorted(initial.revealed_information_ids)),
        )
    return GameState(
        room_id=room_id,
        scene_id=module_content.initial_scene_id,
        actors=dict(actors),
        entities={
            entity.id: dict(entity.state)
            for entity in module_content.entities
        },
        clock=clock or ClockState(),
    )


def _clock_for(module_content: ModuleContentV3) -> ClockState:
    """Start the world clock on the module's declared opening time point (#245)."""

    start_id = module_content.initial_state.start_time_point_id
    if start_id is None:
        return ClockState()
    point = next(
        (
            item
            for item in module_content.time_policy.default_points
            if item.id == start_id
        ),
        None,
    )
    if point is None:
        return ClockState()
    return ClockState(
        elapsed_minutes=point.hour_of_day * 60,
        time_of_day=time_of_day_at(point.hour_of_day * 60),
    )
