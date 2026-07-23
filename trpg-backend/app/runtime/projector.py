"""把完整 GameState 投影成不会泄露 Keeper 信息的 PlayerView。"""

from __future__ import annotations

from typing import Any

from app.module_runtime import RuntimeModule
from app.runtime.checkpoints import checkpoint_bypass_reason, checkpoint_label
from app.runtime.contracts import (
    ActorView,
    CheckpointOption,
    LocationConnectionView,
    PlayerView,
    SceneView,
    VisibleClue,
    VisibleEntity,
    VisibleLocation,
)
from app.runtime.state import GameState


class PlayerViewProjector:
    def project(
        self,
        state: GameState,
        runtime_module: RuntimeModule,
        *,
        actor_id: str,
    ) -> PlayerView:
        actor = state.actors[actor_id]
        scene = runtime_module.get("scenes", state.current_scene_id)
        if scene is None:
            raise ValueError("GameState 指向不存在的场景")

        entities: list[VisibleEntity] = []
        for entity_id in scene.get("entity_ids", []):
            entity = runtime_module.get("entities", entity_id)
            entity_state = state.entity_states.get(entity_id, {})
            if entity is None or entity_state.get("hidden") is True:
                continue
            entities.append(
                VisibleEntity(
                    entity_id=entity_id,
                    name=str(entity.get("name", entity_id)),
                    public_description=entity.get("public_description"),
                )
            )

        clues: list[VisibleClue] = []
        for clue_id in state.granted_clue_ids:
            clue = runtime_module.get("clues", clue_id)
            if clue is None:
                continue
            clues.append(
                VisibleClue(
                    clue_id=clue_id,
                    name=str(clue.get("name") or clue.get("summary") or clue_id),
                    text=str(clue.get("player_facing_text") or clue.get("summary") or ""),
                )
            )

        visible_location_data = [
            location
            for location in runtime_module.package.content.locations
            if self._location_is_visible(
                state.location_states.get(str(location["id"]), {})
            )
        ]
        visible_location_ids = {
            str(location["id"]) for location in visible_location_data
        }
        current_location_ids = [
            location_id
            for location_id in scene.get("location_ids", [])
            if location_id in visible_location_ids
        ]
        current_location_id_set = set(current_location_ids)
        locations: list[VisibleLocation] = []
        for location in visible_location_data:
            connections: list[LocationConnectionView] = []
            connection_candidates = list(location.get("connections", []))
            parent_id = location.get("parent_location_id")
            if parent_id:
                connection_candidates.append(
                    {"location_id": parent_id, "kind": "within_area"}
                )
            for other in visible_location_data:
                other_id = str(other["id"])
                if other.get("parent_location_id") == location["id"]:
                    connection_candidates.append(
                        {"location_id": other_id, "kind": "within_area"}
                    )
                for reverse in other.get("connections", []):
                    if reverse.get("location_id") == location["id"]:
                        connection_candidates.append(
                            {
                                "location_id": other_id,
                                "kind": reverse.get("kind", "route"),
                            }
                        )
            seen_connection_ids: set[str] = set()
            for connection in connection_candidates:
                target_id = str(connection["location_id"])
                if (
                    target_id not in visible_location_ids
                    or target_id in seen_connection_ids
                    or target_id == location["id"]
                ):
                    continue
                target = runtime_module.get("locations", target_id)
                if target is None:
                    continue
                seen_connection_ids.add(target_id)
                connections.append(
                    LocationConnectionView(
                        location_id=target_id,
                        name=str(target["name"]),
                        kind=str(connection.get("kind", "route")),
                    )
                )
            locations.append(
                VisibleLocation(
                    location_id=str(location["id"]),
                    name=str(location["name"]),
                    kind=str(location.get("kind", "location")),
                    parent_location_id=location.get("parent_location_id"),
                    is_current=str(location["id"]) in current_location_id_set,
                    connections=connections,
                )
            )

        checkpoint_ids = list(scene.get("checkpoint_ids", []))
        for timeline_id in state.active_timeline_ids:
            timeline = runtime_module.get("timelines", timeline_id)
            if timeline is None:
                continue
            for timeline_event in timeline.get("events", []):
                schedule = timeline_event.get("schedule", {})
                if state.current_scene_id in timeline_event.get("scene_ids", []) and schedule.get(
                    "time_of_day", state.clock.get("time_of_day")
                ) == state.clock.get("time_of_day"):
                    checkpoint_ids.extend(timeline_event.get("available_checkpoint_ids", []))

        options: list[CheckpointOption] = []
        for checkpoint_id in dict.fromkeys(checkpoint_ids):
            checkpoint = runtime_module.get("checkpoints", checkpoint_id)
            if (
                checkpoint is None
                or checkpoint_id in state.completed_checkpoint_ids
                or not self._prerequisites_met(
                state, checkpoint.get("prerequisites", [])
                )
            ):
                continue
            options.append(
                CheckpointOption(
                    checkpoint_id=checkpoint_id,
                    label=checkpoint_label(checkpoint),
                    skills=list(checkpoint["skills"]),
                    difficulty=str(checkpoint.get("difficulty", "regular")),
                    bypass_reason=checkpoint_bypass_reason(actor, checkpoint),
                )
            )

        return PlayerView(
            room_id=state.room_id,
            room_session_id=state.room_session_id,
            state_revision=state.revision,
            event_sequence=state.event_sequence,
            scene=SceneView(
                scene_id=str(scene["id"]),
                name=str(scene["name"]),
                player_description=str(scene["player_description"]),
                location_ids=current_location_ids,
            ),
            actor=ActorView(
                actor_id=actor.actor_id,
                name=actor.name,
                occupation=actor.occupation,
                attributes=actor.attributes,
                skills=actor.skills,
                current_hp=actor.current_hp,
                current_mp=actor.current_mp,
                current_san=actor.current_san,
            ),
            visible_entities=entities,
            locations=locations,
            clues=clues,
            checkpoint_options=options,
            pending_check=state.pending_checks[0] if state.pending_checks else None,
            active_ending_id=state.active_ending_id,
        )

    @staticmethod
    def _location_is_visible(location_state: dict[str, Any]) -> bool:
        if location_state.get("identified") is False:
            return False
        return location_state.get("discovered") is not False

    @staticmethod
    def _prerequisites_met(state: GameState, prerequisites: list[dict[str, Any]]) -> bool:
        for condition in prerequisites:
            kind = condition.get("type")
            if kind == "clue_not_owned":
                if condition.get("clue_id") in state.granted_clue_ids:
                    return False
            elif kind == "state_eq":
                path = str(condition.get("path"))
                # PlayerView 只需处理《追书人》Checkpoint 的简单状态前置条件。
                value: Any = state.variables.get(path)
                for prefix, bucket in (
                    ("location.", state.location_states),
                    ("object.", state.resource_states),
                    ("item.", state.resource_states),
                    ("npc.", state.entity_states),
                ):
                    if not path.startswith(prefix):
                        continue
                    for item_id, item_state in bucket.items():
                        if path.startswith(item_id + "."):
                            value = item_state.get(path.removeprefix(item_id + "."))
                            break
                if value != condition.get("value"):
                    return False
            else:
                return False
        return True
