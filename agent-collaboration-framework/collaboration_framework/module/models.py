"""Parser-internal intermediate representations.

These models are owned by Member C and must not be imported by Runtime or
shared contract modules. They become shared data only after deterministic
validation constructs ``contracts.ModuleContent``.
"""

from __future__ import annotations

from typing import Any

from pydantic import Field, model_validator

from collaboration_framework.contracts import (
    CheckpointSpec,
    ContractModel,
    EntitySpec,
    InformationItem,
    ModulePresentation,
    RuleSpec,
    SceneSpec,
    WinConditionSpec,
)


class ModuleDraft(ContractModel):
    """Strict Parser IR produced before semantic validation.

    Parser work produces this type rather than ModuleContent. The only
    supported conversion to ModuleContent is the validation boundary.
    """

    source_note: str | None = Field(default=None, alias="_note", exclude=True)
    module_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    world_ref: str = Field(min_length=1)
    background: str = Field(
        min_length=1,
        description="面向叙述 Agent 的时代、地点、玩家侧故事前提与叙事基调。",
    )
    initial_scene_id: str = ""
    scenes: tuple[SceneSpec, ...]
    entities: tuple[EntitySpec, ...]
    checkpoints: tuple[CheckpointSpec, ...]
    win_conditions: tuple[WinConditionSpec, ...]
    module_rules: tuple[RuleSpec, ...] = ()
    information_items: tuple[InformationItem, ...] = ()
    presentation: ModulePresentation | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_legacy_initial_scene(cls, value: Any) -> Any:
        if not isinstance(value, dict) or "initial_scene_id" in value:
            return value
        scenes = value.get("scenes")
        if not isinstance(scenes, (list, tuple)) or not scenes:
            return value
        first_scene = scenes[0]
        scene_id = (
            first_scene.get("id")
            if isinstance(first_scene, dict)
            else getattr(first_scene, "id", None)
        )
        if not scene_id:
            return value
        normalized = dict(value)
        normalized["initial_scene_id"] = scene_id
        return normalized
