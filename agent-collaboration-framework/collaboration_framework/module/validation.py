"""The sole deterministic ModuleDraft -> ModuleContent boundary.

This module performs semantic validation and constructs the shared contract.
It does not parse source material, review, publish, or execute module content.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Literal

from pydantic import ValidationError

from collaboration_framework.contracts import ModifyOperationSpec, ModuleContent

from .models import ModuleDraft


@dataclass(frozen=True)
class ValidationIssue:
    """Stable, caller-safe description of one validation finding."""

    severity: Literal["error", "warning"]
    code: str
    path: str
    message: str


@dataclass(frozen=True)
class ValidationReport:
    """Result returned by the Phase 1 deterministic validation pipeline."""

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
    """Run the structural gate and all deterministic Phase 1 checks."""

    if isinstance(payload, ModuleDraft):
        return validate_draft(payload, skill_catalog=skill_catalog)
    raw_payload = payload.model_dump(mode="python") if isinstance(payload, ModuleContent) else payload
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
    """Parse JSON through the strict private Draft gate, then validate it."""

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
    """Collect all reference and integrity issues without fail-fast behavior."""

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    _check_duplicate_ids(draft, errors)

    scene_ids = {scene.id for scene in draft.scenes}
    entity_ids = {entity.id for entity in draft.entities}
    checkpoint_ids = {checkpoint.id for checkpoint in draft.checkpoints}
    scenes_by_id = {scene.id: scene for scene in draft.scenes}
    known_paths = {
        f"entities.{entity.id}.{key}"
        for entity in draft.entities
        for key in entity.state
    }

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
        _check_operations(
            checkpoint.outcomes.success.ops,
            f"{checkpoint_path}.outcomes.success.ops",
            known_paths,
            errors,
        )
        _check_operations(
            checkpoint.outcomes.failure.ops,
            f"{checkpoint_path}.outcomes.failure.ops",
            known_paths,
            errors,
        )

    for entity_index, entity in enumerate(draft.entities):
        for rule_index, rule in enumerate(entity.rules):
            rule_path = f"entities[{entity_index}].rules[{rule_index}]"
            if rule.when.path not in known_paths:
                errors.append(
                    _error(
                        "rule.ref.state_path_not_found",
                        f"{rule_path}.when.path",
                        f"Rule {rule.id} 引用了未声明的 Entity state 路径。",
                    )
                )
            _check_operations(
                rule.then,
                f"{rule_path}.then",
                known_paths,
                errors,
            )

    for ending_index, ending in enumerate(draft.win_conditions):
        if ending.when.path not in known_paths:
            errors.append(
                _error(
                    "win_condition.ref.state_path_not_found",
                    f"win_conditions[{ending_index}].when.path",
                    f"WinCondition {ending.id} 引用了未声明的 Entity state 路径。",
                )
            )

    if errors:
        return ValidationReport(
            status="needs_revision",
            errors=tuple(errors),
            warnings=tuple(warnings),
        )

    # This is the final publication-contract assertion. It must succeed whenever
    # the private deterministic checks stay aligned with contracts/module.py.
    try:
        content = ModuleContent.model_validate(draft.model_dump(mode="python"))
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
    for entity_index, entity in enumerate(draft.entities):
        for rule_index, rule in enumerate(entity.rules):
            path = f"entities[{entity_index}].rules[{rule_index}].id"
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


def _check_operations(
    operations: tuple,
    path: str,
    known_paths: set[str],
    errors: list[ValidationIssue],
) -> None:
    for operation_index, operation in enumerate(operations):
        if isinstance(operation, ModifyOperationSpec) and operation.path not in known_paths:
            errors.append(
                _error(
                    "operation.ref.state_path_not_found",
                    f"{path}[{operation_index}].path",
                    "Modify Operation 写入了未声明的 Entity state 路径。",
                )
            )


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
            f"Rule hook 不属于 Phase 1 支持目录：{path}。",
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
