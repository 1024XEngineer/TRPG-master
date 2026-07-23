"""把完整 GameState 投影成不会泄露 Keeper 信息的 PlayerView。"""

from __future__ import annotations

from typing import Any

from app.module_runtime import RuntimeModule
from app.runtime.contracts import (
    ActorView,
    CheckpointOption,
    PlayerView,
    SceneView,
    VisibleClue,
    VisibleEntity,
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

        checkpoint_ids = list(scene.get("checkpoint_ids", []))
        for timeline_id in state.active_timeline_ids:
            timeline = runtime_module.get("timelines", timeline_id)
            if timeline is None:
                continue
            for timeline_event in timeline.get("events", []):
                schedule = timeline_event.get("schedule", {})
                if (
                    state.current_scene_id in timeline_event.get("scene_ids", [])
                    and schedule.get("time_of_day", state.clock.get("time_of_day"))
                    == state.clock.get("time_of_day")
                ):
                    checkpoint_ids.extend(
                        timeline_event.get("available_checkpoint_ids", [])
                    )

        options: list[CheckpointOption] = []
        for checkpoint_id in dict.fromkeys(checkpoint_ids):
            checkpoint = runtime_module.get("checkpoints", checkpoint_id)
            if checkpoint is None or not self._prerequisites_met(
                state, checkpoint.get("prerequisites", [])
            ):
                continue
            options.append(
                CheckpointOption(
                    checkpoint_id=checkpoint_id,
                    skills=list(checkpoint["skills"]),
                    difficulty=str(checkpoint.get("difficulty", "regular")),
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
                location_ids=list(scene.get("location_ids", [])),
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
            clues=clues,
            checkpoint_options=options,
            pending_check=state.pending_checks[0] if state.pending_checks else None,
            active_ending_id=state.active_ending_id,
        )

    @staticmethod
    def _prerequisites_met(
        state: GameState, prerequisites: list[dict[str, Any]]
    ) -> bool:
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
