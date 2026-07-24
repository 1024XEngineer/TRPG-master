"""The sole deterministic ModuleDraft -> ModuleContent boundary.

This module validates the parser-owned draft and constructs the B/C shared
publication contract.  It does not execute rules or depend on engine internals.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import ValidationError

from collaboration_framework.contracts import (
    AddOperationSpec,
    ConditionSpec,
    ModifyOperationSpec,
    ModuleContent,
    SetOperationSpec,
    TransitionSpec,
    TriggerEndingSpec,
    TriggerRuleSpec,
)

from .models import ModuleDraft


@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["error", "warning"]
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    status: Literal["pass", "needs_revision", "blocked"]
    content: ModuleContent | None = None
    errors: tuple[ValidationIssue, ...] = ()
    warnings: tuple[ValidationIssue, ...] = ()

    @property
    def is_valid(self) -> bool:
        return self.status == "pass"


def validate_module(
    payload: ModuleContent | ModuleDraft | dict[str, Any],
    *,
    skill_catalog: Collection[str] | None = None,
) -> ValidationReport:
    if isinstance(payload, ModuleDraft):
        return validate_draft(payload, skill_catalog=skill_catalog)
    raw_payload = (
        payload.model_dump(mode="python")
        if isinstance(payload, ModuleContent)
        else payload
    )
    try:
        draft = ModuleDraft.model_validate(raw_payload)
    except ValidationError as error:
        return _schema_failure(error)
    return validate_draft(draft, skill_catalog=skill_catalog)


def validate_module_json(
    payload: str | bytes,
    *,
    skill_catalog: Collection[str] | None = None,
) -> ValidationReport:
    try:
        draft = ModuleDraft.model_validate_json(payload)
    except ValidationError as error:
        return _schema_failure(error)
    return validate_draft(draft, skill_catalog=skill_catalog)


def validate_draft(
    draft: ModuleDraft,
    *,
    skill_catalog: Collection[str] | None = None,
) -> ValidationReport:
    """Collect reference and integrity issues without fail-fast behavior."""

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    _check_duplicate_ids(draft, errors)

    scene_ids = {scene.id for scene in draft.scenes}
    entity_ids = {entity.id for entity in draft.entities}
    checkpoint_ids = {checkpoint.id for checkpoint in draft.checkpoints}
    ending_ids = {ending.id for ending in draft.win_conditions}
    scenes_by_id = {scene.id: scene for scene in draft.scenes}
    state_keys = {
        entity.id: set(entity.state)
        for entity in draft.entities
    }
    rules = [
        *draft.module_rules,
        *(rule for entity in draft.entities for rule in entity.rules),
    ]
    rule_ids = {rule.id for rule in rules}

    for scene_index, scene in enumerate(draft.scenes):
        for entity_index, entity_id in enumerate(scene.entity_ids):
            if entity_id not in entity_ids:
                errors.append(
                    _error(
                        "scene.ref.entity_not_found",
                        f"scenes[{scene_index}].entity_ids[{entity_index}]",
                        f"Scene {scene.id} 引用了不存在的 Entity。",
                    )
                )
        for checkpoint_index, checkpoint_id in enumerate(scene.checkpoint_ids):
            if checkpoint_id not in checkpoint_ids:
                errors.append(
                    _error(
                        "scene.ref.checkpoint_not_found",
                        f"scenes[{scene_index}].checkpoint_ids[{checkpoint_index}]",
                        f"Scene {scene.id} 引用了不存在的 Checkpoint。",
                    )
                )
        for exit_index, exit_id in enumerate(scene.exits):
            if exit_id not in scene_ids:
                errors.append(
                    _error(
                        "scene.ref.exit_not_found",
                        f"scenes[{scene_index}].exits[{exit_index}]",
                        f"Scene {scene.id} 引用了不存在的出口 Scene。",
                    )
                )

    valid_skills = set(skill_catalog) if skill_catalog is not None else None
    for checkpoint_index, checkpoint in enumerate(draft.checkpoints):
        checkpoint_path = f"checkpoints[{checkpoint_index}]"
        scene = scenes_by_id.get(checkpoint.scene_id)
        if checkpoint.scene_id not in scene_ids:
            errors.append(
                _error(
                    "checkpoint.ref.scene_not_found",
                    f"{checkpoint_path}.scene_id",
                    f"Checkpoint {checkpoint.id} 引用了不存在的 Scene。",
                )
            )
        if checkpoint.target_id not in entity_ids:
            errors.append(
                _error(
                    "checkpoint.ref.target_not_found",
                    f"{checkpoint_path}.target_id",
                    f"Checkpoint {checkpoint.id} 引用了不存在的 target Entity。",
                )
            )
        elif scene is not None and checkpoint.target_id not in scene.entity_ids:
            errors.append(
                _error(
                    "checkpoint.ref.target_not_in_scene",
                    f"{checkpoint_path}.target_id",
                    f"Checkpoint {checkpoint.id} 的 target 不属于对应 Scene。",
                )
            )
        if scene is not None and checkpoint.id not in scene.checkpoint_ids:
            errors.append(
                _error(
                    "checkpoint.ref.not_listed_in_scene",
                    checkpoint_path,
                    f"Checkpoint {checkpoint.id} 未列入其所属 Scene。",
                )
            )
        if valid_skills is not None:
            for skill_index, skill in enumerate(checkpoint.skills):
                if skill not in valid_skills:
                    errors.append(
                        _error(
                            "checkpoint.ref.skill_not_found",
                            f"{checkpoint_path}.skills[{skill_index}]",
                            f"Checkpoint {checkpoint.id} 引用了不存在的 Skill。",
                        )
                    )
        for outcome_name, outcome in checkpoint.outcomes:
            if outcome is None:
                continue
            _check_operations(
                outcome.ops,
                f"{checkpoint_path}.outcomes.{outcome_name}.ops",
                state_keys=state_keys,
                scene_ids=scene_ids,
                ending_ids=ending_ids,
                rule_ids=rule_ids,
                errors=errors,
            )

    for rule_index, rule in enumerate(draft.module_rules):
        rule_path = f"module_rules[{rule_index}]"
        _check_condition(
            rule.when,
            f"{rule_path}.when",
            state_keys,
            errors,
            code="rule.ref.state_path_not_found",
        )
        _check_operations(
            rule.then,
            f"{rule_path}.then",
            state_keys=state_keys,
            scene_ids=scene_ids,
            ending_ids=ending_ids,
            rule_ids=rule_ids,
            errors=errors,
        )

    for entity_index, entity in enumerate(draft.entities):
        for rule_index, rule in enumerate(entity.rules):
            rule_path = f"entities[{entity_index}].rules[{rule_index}]"
            _check_condition(
                rule.when,
                f"{rule_path}.when",
                state_keys,
                errors,
                code="rule.ref.state_path_not_found",
            )
            _check_operations(
                rule.then,
                f"{rule_path}.then",
                state_keys=state_keys,
                scene_ids=scene_ids,
                ending_ids=ending_ids,
                rule_ids=rule_ids,
                errors=errors,
            )

    for ending_index, ending in enumerate(draft.win_conditions):
        _check_condition(
            ending.when,
            f"win_conditions[{ending_index}].when",
            state_keys,
            errors,
            code="win_condition.ref.state_path_not_found",
        )

    if errors:
        return ValidationReport(
            status="needs_revision",
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    try:
        content = ModuleContent.model_validate(
            draft.model_dump(mode="python", exclude={"source_note"})
        )
    except ValidationError:
        return ValidationReport(
            status="blocked",
            errors=(
                _error(
                    "validation.contract_mismatch",
                    "$",
                    "Validation Pipeline 与正式 ModuleContent Contract 不一致。",
                ),
            ),
            warnings=tuple(warnings),
        )
    return ValidationReport(
        status="pass",
        content=content,
        warnings=tuple(warnings),
    )


def _check_duplicate_ids(
    draft: ModuleDraft,
    errors: list[ValidationIssue],
) -> None:
    collections = (
        ("scenes", draft.scenes),
        ("entities", draft.entities),
        ("checkpoints", draft.checkpoints),
        ("win_conditions", draft.win_conditions),
        ("information_items", draft.information_items),
    )
    for collection_name, items in collections:
        first_index: dict[str, int] = {}
        for index, item in enumerate(items):
            if item.id in first_index:
                errors.append(
                    _error(
                        "id.duplicate",
                        f"{collection_name}[{index}].id",
                        f"{collection_name} 中存在重复 ID：{item.id}。",
                    )
                )
            else:
                first_index[item.id] = index

    first_rule_path: dict[str, str] = {}
    located_rules = [
        *(
            (f"module_rules[{index}].id", rule)
            for index, rule in enumerate(draft.module_rules)
        ),
        *(
            (f"entities[{entity_index}].rules[{rule_index}].id", rule)
            for entity_index, entity in enumerate(draft.entities)
            for rule_index, rule in enumerate(entity.rules)
        ),
    ]
    for path, rule in located_rules:
        if rule.id in first_rule_path:
            errors.append(
                _error(
                    "id.duplicate",
                    path,
                    f"Rule 中存在重复 ID：{rule.id}。",
                )
            )
        else:
            first_rule_path[rule.id] = path


def _check_condition(
    condition: ConditionSpec,
    path: str,
    state_keys: dict[str, set[str]],
    errors: list[ValidationIssue],
    *,
    code: str,
) -> None:
    if condition.expr is not None:
        return
    if not _is_declared_entity_state_path(condition.path, state_keys):
        errors.append(
            _error(
                code,
                f"{path}.path",
                "Condition 引用了未声明的 Entity state 路径。",
            )
        )


def _check_operations(
    operations: tuple,
    path: str,
    *,
    state_keys: dict[str, set[str]],
    scene_ids: set[str],
    ending_ids: set[str],
    rule_ids: set[str],
    errors: list[ValidationIssue],
) -> None:
    for operation_index, operation in enumerate(operations):
        operation_path = f"{path}[{operation_index}]"
        state_path: str | None = None
        if isinstance(
            operation,
            (
                ModifyOperationSpec,
                SetOperationSpec,
                AddOperationSpec,
            ),
        ):
            state_path = operation.path
        if state_path is not None and not _is_declared_entity_state_path(
            state_path,
            state_keys,
        ):
            errors.append(
                _error(
                    "operation.ref.state_path_not_found",
                    f"{operation_path}.path",
                    "Operation 写入了未声明的 Entity state 路径。",
                )
            )
        if isinstance(operation, TransitionSpec) and operation.scene_id not in scene_ids:
            errors.append(
                _error(
                    "operation.ref.scene_not_found",
                    f"{operation_path}.scene_id",
                    "Transition Operation 引用了不存在的 Scene。",
                )
            )
        if (
            isinstance(operation, TriggerEndingSpec)
            and operation.ending_id not in ending_ids
        ):
            errors.append(
                _error(
                    "operation.ref.ending_not_found",
                    f"{operation_path}.ending_id",
                    "TriggerEnding Operation 引用了不存在的 WinCondition。",
                )
            )
        if isinstance(operation, TriggerRuleSpec) and operation.rule_id not in rule_ids:
            errors.append(
                _error(
                    "operation.ref.rule_not_found",
                    f"{operation_path}.rule_id",
                    "TriggerRule Operation 引用了不存在的 Rule。",
                )
            )


def _is_declared_entity_state_path(
    path: str,
    state_keys: dict[str, set[str]],
) -> bool:
    parts = path.split(".")
    if not parts or parts[0] not in {"entity", "entities"}:
        # self/action/clock/party/scenes and other built-ins belong to the
        # expression/runtime catalog rather than Entity.state declarations.
        return True
    if len(parts) < 3:
        return False
    entity_id = parts[1]
    offset = 3 if parts[2] == "state" else 2
    if len(parts) <= offset:
        return False
    return entity_id in state_keys and parts[offset] in state_keys[entity_id]


def _schema_failure(error: ValidationError) -> ValidationReport:
    issues = tuple(_map_schema_error(item) for item in error.errors(include_url=False))
    return ValidationReport(status="needs_revision", errors=issues)


def _map_schema_error(error: dict[str, Any]) -> ValidationIssue:
    error_type = str(error.get("type", ""))
    location = error.get("loc", ())
    path = _format_path(location)
    if error_type == "json_invalid":
        return _error("schema.invalid_json", "$", "输入不是合法 JSON。")
    if error_type == "missing":
        return _error("schema.missing_field", path, f"缺少必填字段：{path}。")
    if error_type == "extra_forbidden":
        return _error("schema.extra_field", path, f"包含未声明字段：{path}。")
    if error_type == "literal_error" and location and location[-1] == "hook":
        return _error(
            "rule.hook.unsupported",
            path,
            f"Rule hook 不属于当前支持目录：{path}。",
        )
    if error_type == "too_short" and location and location[-1] == "skills":
        return _error(
            "checkpoint.skills.empty",
            path,
            "Checkpoint skills 至少需要一个技能。",
        )
    return _error(
        "schema.invalid",
        path,
        f"字段不符合 ModuleContent Schema：{path}。",
    )


def _error(code: str, path: str, message: str) -> ValidationIssue:
    return ValidationIssue(severity="error", code=code, path=path, message=message)


def _format_path(location: Any) -> str:
    if not location:
        return "$"
    parts: list[str] = []
    for item in location:
        if isinstance(item, int):
            if parts:
                parts[-1] = f"{parts[-1]}[{item}]"
            else:
                parts.append(f"[{item}]")
        else:
            parts.append(str(item))
    return ".".join(parts)
