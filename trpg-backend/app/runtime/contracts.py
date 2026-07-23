"""Loader、主持编排、规则引擎和 WebSocket 共享的稳定数据契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel


class RuntimeModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        alias_generator=to_camel,
        populate_by_name=True,
    )


class PlayerInput(RuntimeModel):
    request_id: str
    room_id: str
    room_session_id: str
    player_id: str
    actor_id: str
    source_revision: int
    utterance: str


class Intent(RuntimeModel):
    kind: Literal["checkpoint", "dialogue", "choice", "free", "unknown"]
    summary: str
    checkpoint_id: str | None = None
    skill_id: str | None = None
    target_id: str | None = None
    choice_id: str | None = None
    approach: str | None = None


class ActionRequest(RuntimeModel):
    request_id: str
    room_id: str
    room_session_id: str
    player_id: str
    actor_id: str
    source_revision: int
    utterance: str
    intent: Intent


class RuntimeEvent(RuntimeModel):
    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    visibility: Literal["room", "player", "keeper"] = "room"


class PendingCheck(RuntimeModel):
    check_request_id: str
    kind: Literal["skill", "san"]
    actor_id: str
    checkpoint_id: str | None = None
    sanity_event_id: str | None = None
    skill_id: str | None = None
    target_value: int
    difficulty: str = "regular"
    reason: str


class ActionResult(RuntimeModel):
    request_id: str
    resolution: Literal["resolved", "pending_check", "replayed", "rejected"]
    outcome: str
    state_revision: int
    state_changed: bool
    pending_check: PendingCheck | None = None
    events: list[RuntimeEvent] = Field(default_factory=list)
    narration_facts: list[str] = Field(default_factory=list)


class ActorView(RuntimeModel):
    actor_id: str
    name: str
    occupation: str | None = None
    attributes: dict[str, int] = Field(default_factory=dict)
    skills: dict[str, int] = Field(default_factory=dict)
    current_hp: int
    current_mp: int
    current_san: int


class SceneView(RuntimeModel):
    scene_id: str
    name: str
    player_description: str
    location_ids: list[str] = Field(default_factory=list)


class VisibleEntity(RuntimeModel):
    entity_id: str
    name: str
    public_description: str | None = None


class VisibleClue(RuntimeModel):
    clue_id: str
    name: str
    text: str


class LocationConnectionView(RuntimeModel):
    location_id: str
    name: str
    kind: str


class VisibleLocation(RuntimeModel):
    location_id: str
    name: str
    kind: str
    parent_location_id: str | None = None
    is_current: bool = False
    connections: list[LocationConnectionView] = Field(default_factory=list)


class CheckpointOption(RuntimeModel):
    checkpoint_id: str
    label: str
    skills: list[str]
    difficulty: str
    bypass_reason: str | None = None


class PlayerView(RuntimeModel):
    room_id: str
    room_session_id: str
    state_revision: int
    event_sequence: int
    scene: SceneView
    actor: ActorView
    visible_entities: list[VisibleEntity] = Field(default_factory=list)
    locations: list[VisibleLocation] = Field(default_factory=list)
    clues: list[VisibleClue] = Field(default_factory=list)
    checkpoint_options: list[CheckpointOption] = Field(default_factory=list)
    pending_check: PendingCheck | None = None
    active_ending_id: str | None = None


class NarrationOutput(RuntimeModel):
    text: str
    referenced_fact_ids: list[str] = Field(default_factory=list)


class TurnResult(RuntimeModel):
    action: ActionResult
    narration: NarrationOutput
    view: PlayerView
