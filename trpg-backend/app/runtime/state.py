"""持久化 GameState 的强类型模型及首局初始化。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.room import Character
from app.module_runtime.loader import RuntimeModule
from app.runtime.contracts import PendingCheck


class ActorState(BaseModel):
    model_config = ConfigDict(extra="allow")

    actor_id: str
    name: str
    occupation: str | None = None
    attributes: dict[str, int] = Field(default_factory=dict)
    derived_stats: dict[str, int | str] = Field(default_factory=dict)
    skills: dict[str, int] = Field(default_factory=dict)
    equipment: list[str] = Field(default_factory=list)
    current_hp: int
    current_mp: int
    current_san: int
    max_san: int
    currency: dict[str, int] = Field(default_factory=lambda: {"USD": 20})


class GameState(BaseModel):
    model_config = ConfigDict(extra="allow")

    room_id: str
    room_session_id: str
    scenario_revision_id: str
    revision: int = 0
    event_sequence: int = 0
    current_scene_id: str
    discovered_scene_ids: list[str] = Field(default_factory=list)
    granted_clue_ids: list[str] = Field(default_factory=list)
    completed_checkpoint_ids: list[str] = Field(default_factory=list)
    fired_trigger_ids: list[str] = Field(default_factory=list)
    active_timeline_ids: list[str] = Field(default_factory=list)
    track_states: dict[str, Any] = Field(default_factory=dict)
    inventory_resource_ids: list[str] = Field(default_factory=list)
    active_encounter_id: str | None = None
    active_ending_id: str | None = None
    clock: dict[str, Any] = Field(default_factory=lambda: {"day": 0, "time_of_day": "day"})
    variables: dict[str, Any] = Field(default_factory=dict)
    location_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    entity_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    resource_states: dict[str, dict[str, Any]] = Field(default_factory=dict)
    actors: dict[str, ActorState] = Field(default_factory=dict)
    pending_checks: list[PendingCheck] = Field(default_factory=list)
    last_intent: dict[str, Any] | None = None
    last_check: dict[str, Any] | None = None

    @classmethod
    def create(
        cls,
        *,
        room_id: str,
        room_session_id: str,
        scenario_revision_id: str,
        runtime_module: RuntimeModule,
        character: Character,
    ) -> GameState:
        initial = runtime_module.package.initial_state.model_dump(mode="json")
        attributes = {key: int(value) for key, value in (character.attributes or {}).items()}
        derived = dict(character.derived_stats or {})
        skills = {key: int(value) for key, value in (character.skills or {}).items()}
        san = int(derived.get("SAN", attributes.get("POW", 50)))
        actor = ActorState(
            actor_id=character.id,
            name=character.name or "未命名调查员",
            occupation=character.occupation,
            attributes=attributes,
            derived_stats=derived,
            skills=skills,
            equipment=list(character.equipment or []),
            current_hp=int(derived.get("HP", 1)),
            current_mp=int(derived.get("MP", 0)),
            current_san=san,
            max_san=max(0, 99 - skills.get("cthulhu_mythos", 0)),
        )
        return cls(
            room_id=room_id,
            room_session_id=room_session_id,
            scenario_revision_id=scenario_revision_id,
            **initial,
            location_states={
                item["id"]: dict(item.get("initial_state", {}))
                for item in runtime_module.package.content.locations
            },
            entity_states={
                item["id"]: dict(item.get("initial_state", {}))
                for item in runtime_module.package.content.entities
            },
            resource_states={
                item["id"]: dict(item.get("initial_state", {}))
                for item in runtime_module.package.content.resources
            },
            actors={character.id: actor},
        )
