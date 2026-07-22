"""Published module language jointly reviewed by module and engine owners.

These models describe what a module declares. They do not execute rules, roll
dice, mutate GameState, or append Events.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, JsonValue, model_validator

from .common import ContractModel


class ConditionSpec(ContractModel):
    path: str = Field(min_length=1)
    equals: JsonValue


class AllowOperationSpec(ContractModel):
    op: Literal["allow"] = "allow"
    action: str = Field(min_length=1)


class ModifyOperationSpec(ContractModel):
    op: Literal["modify"] = "modify"
    path: str = Field(min_length=1)
    set: JsonValue


OperationSpec = Annotated[
    AllowOperationSpec | ModifyOperationSpec,
    Field(discriminator="op"),
]


class RuleSpec(ContractModel):
    id: str = Field(min_length=1)
    hook: Literal["on_action", "on_scene_enter", "on_turn_end", "on_check_resolve"]
    priority: int = 0
    when: ConditionSpec
    then: tuple[OperationSpec, ...] = ()
    facts: tuple[str, ...] = ()
    player_visible_information: tuple[str, ...] = ()


class SceneSpec(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    content: str
    entity_ids: tuple[str, ...] = ()
    checkpoint_ids: tuple[str, ...] = ()


class EntitySpec(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    content: str
    secrets: str | None = None
    state: dict[str, JsonValue] = Field(default_factory=dict)
    refuse_ops: tuple[str, ...] = ()
    blocked_text: str | None = None
    direct_responses: dict[str, str] = Field(default_factory=dict)
    rules: tuple[RuleSpec, ...] = ()


class CheckpointOutcomeSpec(ContractModel):
    facts: tuple[str, ...] = ()
    player_visible_information: tuple[str, ...] = ()
    narration_constraints: tuple[str, ...] = ()
    ops: tuple[OperationSpec, ...] = ()


class CheckpointOutcomesSpec(ContractModel):
    success: CheckpointOutcomeSpec
    failure: CheckpointOutcomeSpec


class CheckpointSpec(ContractModel):
    id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    # Semantic hint for the host Agent. It is not an exhaustive verb allow-list.
    action: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    skills: tuple[str, ...] = Field(min_length=1)
    difficulty: Literal["regular", "hard", "extreme"]
    # Demo-only fixture. The production engine owns authoritative check results.
    mvp_check_result: Literal["success", "failure"] = "success"
    outcomes: CheckpointOutcomesSpec


class WinConditionSpec(ContractModel):
    id: str = Field(min_length=1)
    when: ConditionSpec
    fact: str
    player_visible_information: str


class ModuleContent(ContractModel):
    """Validated, versioned module publication consumed by runtime components."""

    module_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    world_ref: str = Field(min_length=1)
    scenes: tuple[SceneSpec, ...]
    entities: tuple[EntitySpec, ...]
    checkpoints: tuple[CheckpointSpec, ...]
    win_conditions: tuple[WinConditionSpec, ...]

    @model_validator(mode="after")
    def validate_references(self) -> ModuleContent:
        collections = {
            "Scene": [item.id for item in self.scenes],
            "Entity": [item.id for item in self.entities],
            "Checkpoint": [item.id for item in self.checkpoints],
            "WinCondition": [item.id for item in self.win_conditions],
        }
        for label, ids in collections.items():
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} id 必须唯一")

        scene_ids = set(collections["Scene"])
        entity_ids = set(collections["Entity"])
        checkpoint_ids = set(collections["Checkpoint"])
        scenes_by_id = {scene.id: scene for scene in self.scenes}

        for scene in self.scenes:
            if missing := set(scene.entity_ids) - entity_ids:
                raise ValueError(f"Scene {scene.id} 引用了不存在的 Entity: {sorted(missing)}")
            if missing := set(scene.checkpoint_ids) - checkpoint_ids:
                raise ValueError(
                    f"Scene {scene.id} 引用了不存在的 Checkpoint: {sorted(missing)}"
                )

        for checkpoint in self.checkpoints:
            if checkpoint.scene_id not in scene_ids:
                raise ValueError(f"Checkpoint {checkpoint.id} 的 Scene 不存在")
            if checkpoint.target_id not in entity_ids:
                raise ValueError(f"Checkpoint {checkpoint.id} 的 target 不存在")
            if checkpoint.id not in scenes_by_id[checkpoint.scene_id].checkpoint_ids:
                raise ValueError(
                    f"Checkpoint {checkpoint.id} 未列入 Scene {checkpoint.scene_id}"
                )

        known_paths = {
            f"entities.{entity.id}.{key}"
            for entity in self.entities
            for key in entity.state
        }
        for entity in self.entities:
            for rule in entity.rules:
                self._validate_condition(rule.when, known_paths, f"Rule {rule.id}")
                self._validate_operations(rule.then, known_paths, f"Rule {rule.id}")
        for checkpoint in self.checkpoints:
            self._validate_operations(
                checkpoint.outcomes.success.ops,
                known_paths,
                f"Checkpoint {checkpoint.id}.success",
            )
            self._validate_operations(
                checkpoint.outcomes.failure.ops,
                known_paths,
                f"Checkpoint {checkpoint.id}.failure",
            )
        for ending in self.win_conditions:
            self._validate_condition(ending.when, known_paths, f"WinCondition {ending.id}")
        return self

    @staticmethod
    def _validate_condition(
        condition: ConditionSpec,
        paths: set[str],
        owner: str,
    ) -> None:
        if condition.path not in paths:
            raise ValueError(f"{owner} 引用了不存在的状态路径 {condition.path}")

    @staticmethod
    def _validate_operations(
        operations: tuple[OperationSpec, ...],
        paths: set[str],
        owner: str,
    ) -> None:
        for operation in operations:
            if isinstance(operation, ModifyOperationSpec) and operation.path not in paths:
                raise ValueError(f"{owner} 写入了不存在的状态路径 {operation.path}")


# Compatibility aliases for the current fixtures and engine implementation.
Condition = ConditionSpec
AllowOperation = AllowOperationSpec
ModifyOperation = ModifyOperationSpec
Operation = OperationSpec
Rule = RuleSpec
Scene = SceneSpec
Entity = EntitySpec
CheckpointOutcome = CheckpointOutcomeSpec
CheckpointOutcomes = CheckpointOutcomesSpec
Checkpoint = CheckpointSpec
WinCondition = WinConditionSpec
