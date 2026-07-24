"""Published module language jointly reviewed by module and engine owners.

The module team publishes this declarative contract.  The engine may support
only a subset of the declared hooks, expressions, and operations while its
runtime implementation is still a placeholder, but it must not narrow or
silently rewrite the publication language.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, TypeAlias

from pydantic import Field, JsonValue, model_serializer, model_validator

from .common import ContractModel

RuleHook: TypeAlias = Literal[
    "on_attack_declare",
    "on_difficulty_calc",
    "on_attack_roll",
    "on_dodge_declare",
    "on_dodge_roll",
    "on_hit_resolve",
    "on_damage_roll",
    "on_armor_apply",
    "on_hp_write",
    "on_major_wound",
    "on_death",
    "on_turn_end",
    "on_check_declare",
    "on_check_roll",
    "on_check_resolve",
    "on_scene_enter",
    "on_scene_exit",
    "on_interact",
    "on_state_change",
    "on_time_elapsed",
]


class ConditionSpec(ContractModel):
    """Exactly one of ``path + equals`` or ``expr``."""

    path: str = ""
    equals: JsonValue | None = None
    expr: str | None = None

    @model_validator(mode="after")
    def validate_form(self) -> ConditionSpec:
        has_path = bool(self.path)
        has_equals = "equals" in self.model_fields_set
        has_expr = bool(self.expr)
        if has_path != has_equals or has_expr == (has_path and has_equals):
            raise ValueError("Condition 必须且只能使用 path+equals 或 expr")
        return self

    @model_serializer
    def serialize_form(self) -> dict[str, JsonValue]:
        """Emit only the selected form so nested contract dumps round-trip."""

        if self.expr is not None:
            return {"expr": self.expr}
        return {"path": self.path, "equals": self.equals}


class VisibilityPolicy(ContractModel):
    audience: Literal["all", "actor", "ho", "keeper"] = "all"
    ho_ref: str | None = None
    requires_discovery: bool = False
    discovery_rule: str | None = None
    discovery_shares_to_party: bool = True

    @model_validator(mode="after")
    def validate_policy(self) -> VisibilityPolicy:
        if self.audience == "ho" and not self.ho_ref:
            raise ValueError("audience=ho 时必须提供 ho_ref")
        if self.audience != "ho" and self.ho_ref is not None:
            raise ValueError("只有 audience=ho 时可以提供 ho_ref")
        if not self.requires_discovery and self.discovery_rule is not None:
            raise ValueError("discovery_rule 要求 requires_discovery=true")
        return self


class VisibleInformation(ContractModel):
    text: str
    visibility: VisibilityPolicy = Field(default_factory=VisibilityPolicy)

    @model_validator(mode="before")
    @classmethod
    def accept_legacy_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return {"text": value}
        return value


class AllowOperationSpec(ContractModel):
    op: Literal["allow"] = "allow"
    action: str = Field(min_length=1)


class ModifyOperationSpec(ContractModel):
    op: Literal["modify"] = "modify"
    path: str = Field(min_length=1)
    set: JsonValue


class SetOperationSpec(ContractModel):
    op: Literal["set"] = "set"
    path: str = Field(min_length=1)
    value: JsonValue


class ScaleOperationSpec(ContractModel):
    op: Literal["scale"] = "scale"
    value: float
    round: Literal["floor", "ceil"] | None = None


class AddOperationSpec(ContractModel):
    op: Literal["add"] = "add"
    path: str = Field(min_length=1)
    value: JsonValue


class AbsorbOperationSpec(ContractModel):
    op: Literal["absorb"] = "absorb"
    amount: str = Field(min_length=1)
    decrement: str = Field(min_length=1)


class ForbidOperationSpec(ContractModel):
    op: Literal["forbid"] = "forbid"


class ForceOperationSpec(ContractModel):
    op: Literal["force"] = "force"
    action: str = Field(min_length=1)


class ApplyConditionSpec(ContractModel):
    op: Literal["apply_condition"] = "apply_condition"
    condition: str = Field(min_length=1)


class TriggerEndingSpec(ContractModel):
    op: Literal["trigger_ending"] = "trigger_ending"
    ending_id: str = Field(min_length=1)


class TriggerRuleSpec(ContractModel):
    op: Literal["trigger_rule"] = "trigger_rule"
    rule_id: str = Field(min_length=1)


class TransitionSpec(ContractModel):
    op: Literal["transition"] = "transition"
    scene_id: str = Field(min_length=1)


OperationSpec = Annotated[
    AllowOperationSpec
    | ModifyOperationSpec
    | SetOperationSpec
    | ScaleOperationSpec
    | AddOperationSpec
    | AbsorbOperationSpec
    | ForbidOperationSpec
    | ForceOperationSpec
    | ApplyConditionSpec
    | TriggerEndingSpec
    | TriggerRuleSpec
    | TransitionSpec,
    Field(discriminator="op"),
]


class RuleSpec(ContractModel):
    id: str = Field(min_length=1)
    hook: RuleHook
    priority: int = 0
    mode: Literal["append", "override", "forbid"] = "append"
    when: ConditionSpec
    then: tuple[OperationSpec, ...] = ()
    facts: tuple[str, ...] = ()
    player_visible_information: tuple[VisibleInformation, ...] = ()

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_hook(cls, value: Any) -> Any:
        if isinstance(value, dict) and value.get("hook") == "on_action":
            normalized = dict(value)
            normalized["hook"] = "on_interact"
            return normalized
        return value


class SceneSpec(ContractModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    content: str
    entity_ids: tuple[str, ...] = ()
    checkpoint_ids: tuple[str, ...] = ()
    exits: tuple[str, ...] = ()


class StatBlock(ContractModel):
    STR: int | None = None
    CON: int | None = None
    SIZ: int | None = None
    INT: int | None = None
    POW: int | None = None
    DEX: int | None = None
    APP: int | None = None
    EDU: int | None = None
    SAN: int | None = None
    HP: int | None = None
    MP: int | None = None
    MOV: int | None = None
    armor: str | None = None
    move: int | None = None


class EntitySpec(ContractModel):
    id: str = Field(min_length=1)
    kind: Literal["npc", "object", "location"]
    name: str = Field(min_length=1)
    aliases: tuple[str, ...] = ()
    content: str
    secrets: str | None = None
    information_item_ids: tuple[str, ...] = ()
    state: dict[str, JsonValue] = Field(default_factory=dict)
    refuse_ops: tuple[str, ...] = ()
    blocked_text: str | None = None
    direct_responses: dict[str, str] = Field(default_factory=dict)
    rules: tuple[RuleSpec, ...] = ()
    stat_block: StatBlock | None = None


class CheckpointOutcomeSpec(ContractModel):
    facts: tuple[str, ...] = ()
    player_visible_information: tuple[VisibleInformation, ...] = ()
    narration_constraints: tuple[str, ...] = ()
    ops: tuple[OperationSpec, ...] = ()


class CheckpointOutcomesSpec(ContractModel):
    success: CheckpointOutcomeSpec
    failure: CheckpointOutcomeSpec
    critical_success: CheckpointOutcomeSpec | None = None
    extreme_success: CheckpointOutcomeSpec | None = None
    hard_success: CheckpointOutcomeSpec | None = None
    regular_success: CheckpointOutcomeSpec | None = None
    fumble: CheckpointOutcomeSpec | None = None


class CheckpointSpec(ContractModel):
    id: str = Field(min_length=1)
    scene_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    target_id: str = Field(min_length=1)
    skills: tuple[str, ...] = ()
    difficulty: Literal["regular", "hard", "extreme"] | None = None
    outcomes: CheckpointOutcomesSpec
    visibility: VisibilityPolicy | None = None

    @model_validator(mode="before")
    @classmethod
    def discard_legacy_test_outcome(cls, value: Any) -> Any:
        if isinstance(value, dict) and "mvp_check_result" in value:
            normalized = dict(value)
            normalized.pop("mvp_check_result", None)
            return normalized
        return value


class WinConditionSpec(ContractModel):
    id: str = Field(min_length=1)
    when: ConditionSpec
    fact: str
    player_visible_information: str
    is_ending: bool = True


class InformationItem(ContractModel):
    id: str = Field(min_length=1)
    content: str
    visibility: VisibilityPolicy = Field(default_factory=VisibilityPolicy)

    @model_validator(mode="after")
    def validate_static_visibility(self) -> InformationItem:
        if self.visibility.requires_discovery:
            raise ValueError("InformationItem 不得声明 discovery 规则")
        return self


class ModuleContent(ContractModel):
    """Validated, versioned module publication consumed by runtime components."""

    module_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    world_ref: str = Field(min_length=1)
    background: str = Field(
        min_length=1,
        description="面向叙述 Agent 的时代、地点、玩家侧故事前提与叙事基调。",
    )
    scenes: tuple[SceneSpec, ...]
    entities: tuple[EntitySpec, ...]
    checkpoints: tuple[CheckpointSpec, ...]
    win_conditions: tuple[WinConditionSpec, ...]
    module_rules: tuple[RuleSpec, ...] = ()
    information_items: tuple[InformationItem, ...] = ()

    @model_validator(mode="after")
    def validate_references(self) -> ModuleContent:
        collections = {
            "Scene": [item.id for item in self.scenes],
            "Entity": [item.id for item in self.entities],
            "Checkpoint": [item.id for item in self.checkpoints],
            "WinCondition": [item.id for item in self.win_conditions],
            "InformationItem": [item.id for item in self.information_items],
        }
        for label, ids in collections.items():
            if len(ids) != len(set(ids)):
                raise ValueError(f"{label} id 必须唯一")

        rules = [
            *self.module_rules,
            *(rule for entity in self.entities for rule in entity.rules),
        ]
        rule_ids = [rule.id for rule in rules]
        if len(rule_ids) != len(set(rule_ids)):
            raise ValueError("Rule id 必须在 ModuleContent 内唯一")

        scene_ids = set(collections["Scene"])
        entity_ids = set(collections["Entity"])
        checkpoint_ids = set(collections["Checkpoint"])
        ending_ids = set(collections["WinCondition"])
        information_item_ids = set(collections["InformationItem"])
        rule_id_set = set(rule_ids)
        scenes_by_id = {scene.id: scene for scene in self.scenes}
        entities_by_id = {entity.id: entity for entity in self.entities}

        for scene in self.scenes:
            if missing := set(scene.entity_ids) - entity_ids:
                raise ValueError(f"Scene {scene.id} 引用了不存在的 Entity: {sorted(missing)}")
            if missing := set(scene.checkpoint_ids) - checkpoint_ids:
                raise ValueError(
                    f"Scene {scene.id} 引用了不存在的 Checkpoint: {sorted(missing)}"
                )
            if missing := set(scene.exits) - scene_ids:
                raise ValueError(f"Scene {scene.id} 引用了不存在的 exit: {sorted(missing)}")

        for entity in self.entities:
            if missing := set(entity.information_item_ids) - information_item_ids:
                raise ValueError(
                    f"Entity {entity.id} 引用了不存在的 InformationItem: {sorted(missing)}"
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
            if checkpoint.target_id not in scenes_by_id[checkpoint.scene_id].entity_ids:
                raise ValueError(
                    f"Checkpoint {checkpoint.id} 的 target 不属于 Scene {checkpoint.scene_id}"
                )

        for rule in rules:
            self._validate_condition(rule.when, entities_by_id, f"Rule {rule.id}")
            self._validate_operations(
                rule.then,
                entities_by_id,
                scene_ids,
                ending_ids,
                rule_id_set,
                f"Rule {rule.id}",
            )
        for checkpoint in self.checkpoints:
            for outcome_name, outcome in checkpoint.outcomes:
                if outcome is None:
                    continue
                self._validate_operations(
                    outcome.ops,
                    entities_by_id,
                    scene_ids,
                    ending_ids,
                    rule_id_set,
                    f"Checkpoint {checkpoint.id}.{outcome_name}",
                )
        for ending in self.win_conditions:
            self._validate_condition(
                ending.when,
                entities_by_id,
                f"WinCondition {ending.id}",
            )
        return self

    @classmethod
    def _validate_condition(
        cls,
        condition: ConditionSpec,
        entities_by_id: dict[str, EntitySpec],
        owner: str,
    ) -> None:
        if condition.expr is not None:
            return
        cls._validate_state_path(condition.path, entities_by_id, owner)

    @classmethod
    def _validate_operations(
        cls,
        operations: tuple[OperationSpec, ...],
        entities_by_id: dict[str, EntitySpec],
        scene_ids: set[str],
        ending_ids: set[str],
        rule_ids: set[str],
        owner: str,
    ) -> None:
        for operation in operations:
            if isinstance(
                operation,
                (ModifyOperationSpec, SetOperationSpec, AddOperationSpec),
            ):
                cls._validate_state_path(operation.path, entities_by_id, owner)
            elif isinstance(operation, TransitionSpec):
                if operation.scene_id not in scene_ids:
                    raise ValueError(
                        f"{owner} 跳转到不存在的 Scene {operation.scene_id}"
                    )
            elif isinstance(operation, TriggerEndingSpec):
                if operation.ending_id not in ending_ids:
                    raise ValueError(
                        f"{owner} 触发不存在的 WinCondition {operation.ending_id}"
                    )
            elif (
                isinstance(operation, TriggerRuleSpec)
                and operation.rule_id not in rule_ids
            ):
                raise ValueError(
                    f"{owner} 触发不存在的 Rule {operation.rule_id}"
                )

    @staticmethod
    def _validate_state_path(
        path: str,
        entities_by_id: dict[str, EntitySpec],
        owner: str,
    ) -> None:
        parts = path.split(".")
        if not parts:
            raise ValueError(f"{owner} 使用了空状态路径")
        if parts[0] not in {"entity", "entities"}:
            return
        if len(parts) < 3:
            raise ValueError(f"{owner} 使用了不完整的实体状态路径 {path}")
        entity_id = parts[1]
        entity = entities_by_id.get(entity_id)
        if entity is None:
            raise ValueError(f"{owner} 引用了不存在的 Entity {entity_id}")
        state_offset = 3 if len(parts) > 2 and parts[2] == "state" else 2
        if len(parts) <= state_offset:
            raise ValueError(f"{owner} 使用了不完整的实体状态路径 {path}")
        state_key = parts[state_offset]
        if state_key not in entity.state:
            raise ValueError(f"{owner} 引用了未声明的状态路径 {path}")


# Compatibility aliases retained for existing engine and backend imports.
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
