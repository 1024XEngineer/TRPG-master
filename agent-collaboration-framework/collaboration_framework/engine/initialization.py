"""Construct authoritative room state from one published ModuleContent."""

from __future__ import annotations

from collections.abc import Mapping

from collaboration_framework.contracts import ModuleContent

from .models import ActorState, ClockState, GameState


def create_initial_game_state(
    module_content: ModuleContent,
    *,
    room_id: str,
    actors: Mapping[str, ActorState],
    clock: ClockState | None = None,
) -> GameState:
    """Hydrate the module-declared opening scene and entity state defaults."""

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
