"""Semantic validation for ModuleContent v3 (#212 §13.1).

`ModuleContentV3` already enforces everything a single object can check on its
own: shapes, enums, unique ids inside one collection, a rule's step graph being
internally connected. What it cannot see is the rest of the module — whether a
goal names an Information that exists, whether an edge connects two real
Locations, whether an `agent_match` option can ever reach a branch.

Those are the checks that live here, and they deliberately **collect** rather
than raise: a module author fixing a 2000-line file wants every problem in one
report, not one per run. This mirrors the v2 `ValidationReport` contract so
Publisher tooling can treat both versions the same way.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from collaboration_framework.contracts.module_v3 import (
    AdjudicatedCheckStep,
    AgentMatchTriggerSpec,
    AllCondition,
    AnyCondition,
    CheckStep,
    ConditionExpr,
    CreateNpcActionOpportunityStep,
    EffectStep,
    EventTriggerSpec,
    ModuleContentV3,
    NotCondition,
    PredicateCondition,
    RuleSpecV3,
)

from .validation import ValidationIssue, ValidationReport

# Effects carry their referenced ids under different field names; this maps each
# one to the collection that must contain it.
_EFFECT_REFERENCES: dict[str, tuple[str, str]] = {
    "information_id": ("information", "MODULE_V3_INFORMATION_NOT_FOUND"),
    "location_id": ("locations", "MODULE_V3_LOCATION_NOT_FOUND"),
    "entity_id": ("entities", "MODULE_V3_ENTITY_NOT_FOUND"),
}


def validate_module_v3(payload: ModuleContentV3 | dict[str, Any]) -> ValidationReport:
    """Validate a v3 module, returning every problem found."""

    if isinstance(payload, ModuleContentV3):
        content = payload
    else:
        try:
            content = ModuleContentV3.model_validate(payload)
        except ValidationError as error:
            return _schema_failure(error)
    errors = _semantic_issues(content)
    if errors:
        return ValidationReport(status="needs_revision", errors=tuple(errors))
    return ValidationReport(status="pass")


def validate_module_v3_json(payload: str | bytes) -> ValidationReport:
    try:
        content = ModuleContentV3.model_validate_json(payload)
    except ValidationError as error:
        return _schema_failure(error)
    return validate_module_v3(content)


def _schema_failure(error: ValidationError) -> ValidationReport:
    issues = tuple(
        ValidationIssue(
            severity="error",
            code="MODULE_V3_SCHEMA_INVALID",
            path=".".join(str(part) for part in issue.get("loc", ())) or "$",
            message=str(issue.get("msg", "schema validation failed")),
        )
        for issue in error.errors(include_url=False, include_context=False, include_input=False)
    )
    return ValidationReport(status="blocked", errors=issues)


def _semantic_issues(content: ModuleContentV3) -> list[ValidationIssue]:
    information_ids = {item.id for item in content.information}
    entity_ids = {item.id for item in content.entities}
    location_ids = {item.id for item in content.locations}
    goal_ids = {item.id for item in content.knowledge_goals}
    anchor_ids = {item.id for item in content.ending_anchors}
    time_point_ids = {point.id for point in content.time_policy.default_points}
    known = {
        "information": information_ids,
        "entities": entity_ids,
        "locations": location_ids,
    }

    issues: list[ValidationIssue] = []

    def require(value: str | None, collection: str, code: str, path: str) -> None:
        if value is None:
            return
        if value not in known[collection]:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code=code,
                    path=path,
                    message=f"引用了不存在的 {collection[:-1]}: {value}",
                )
            )

    # --- knowledge goals -------------------------------------------------- #
    for index, goal in enumerate(content.knowledge_goals):
        for target in goal.target_information_ids:
            require(
                target,
                "information",
                "MODULE_V3_INFORMATION_NOT_FOUND",
                f"knowledge_goals.{index}.target_information_ids",
            )

    # --- entities ---------------------------------------------------------- #
    for index, entity in enumerate(content.entities):
        require(
            entity.located_in,
            "locations",
            "MODULE_V3_LOCATION_NOT_FOUND",
            f"entities.{index}.located_in",
        )
        for relation_index, relation in enumerate(entity.relations):
            if (
                relation.target_id not in entity_ids
                and relation.target_id not in location_ids
            ):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="MODULE_V3_RELATION_TARGET_NOT_FOUND",
                        path=f"entities.{index}.relations.{relation_index}.target_id",
                        message=f"关系目标既不是 Entity 也不是 Location: {relation.target_id}",
                    )
                )

    # --- locations --------------------------------------------------------- #
    for index, location in enumerate(content.locations):
        require(
            location.parent_location_id,
            "locations",
            "MODULE_V3_LOCATION_NOT_FOUND",
            f"locations.{index}.parent_location_id",
        )
        require(
            location.region_id,
            "locations",
            "MODULE_V3_LOCATION_NOT_FOUND",
            f"locations.{index}.region_id",
        )
    issues.extend(_location_cycle_issues(content))

    for index, edge in enumerate(content.location_edges):
        require(
            edge.from_location_id,
            "locations",
            "MODULE_V3_LOCATION_NOT_FOUND",
            f"location_edges.{index}.from_location_id",
        )
        require(
            edge.to_location_id,
            "locations",
            "MODULE_V3_LOCATION_NOT_FOUND",
            f"location_edges.{index}.to_location_id",
        )
        require(
            edge.access_point_id,
            "entities",
            "MODULE_V3_ENTITY_NOT_FOUND",
            f"location_edges.{index}.access_point_id",
        )
        for condition_index, condition in enumerate(edge.conditions):
            issues.extend(
                _condition_issues(
                    condition,
                    f"location_edges.{index}.conditions.{condition_index}",
                )
            )

    # --- rules ------------------------------------------------------------- #
    for index, rule in enumerate(content.rules):
        issues.extend(_rule_issues(rule, f"rules.{index}", known, require))

    # --- resolution and endings -------------------------------------------- #
    for index, goal_id in enumerate(content.core_resolution.required_goal_ids):
        if goal_id not in goal_ids:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="MODULE_V3_GOAL_NOT_FOUND",
                    path=f"core_resolution.required_goal_ids.{index}",
                    message=f"引用了不存在的 KnowledgeGoal: {goal_id}",
                )
            )
    for index, anchor in enumerate(content.ending_anchors):
        for ref_index, fact_ref in enumerate(anchor.required_fact_refs):
            if fact_ref not in information_ids:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="MODULE_V3_INFORMATION_NOT_FOUND",
                        path=f"ending_anchors.{index}.required_fact_refs.{ref_index}",
                        message=f"结局锚点引用了不存在的 Information: {fact_ref}",
                    )
                )
    if content.ending_policy.facets and anchor_ids and not content.ending_anchors:
        issues.append(
            ValidationIssue(
                severity="error",
                code="MODULE_V3_ENDING_ANCHOR_MISSING",
                path="ending_anchors",
                message="声明了 ending facets 但没有任何结局锚点",
            )
        )

    # --- initial state ------------------------------------------------------ #
    require(
        content.initial_state.start_location_id,
        "locations",
        "MODULE_V3_LOCATION_NOT_FOUND",
        "initial_state.start_location_id",
    )
    if content.initial_state.default_actor_placement is not None:
        require(
            content.initial_state.default_actor_placement.location_id,
            "locations",
            "MODULE_V3_LOCATION_NOT_FOUND",
            "initial_state.default_actor_placement.location_id",
        )
    for index, information_id in enumerate(content.initial_state.revealed_information_ids):
        require(
            information_id,
            "information",
            "MODULE_V3_INFORMATION_NOT_FOUND",
            f"initial_state.revealed_information_ids.{index}",
        )
    for entity_id in sorted(content.initial_state.entity_state):
        require(
            entity_id,
            "entities",
            "MODULE_V3_ENTITY_NOT_FOUND",
            f"initial_state.entity_state.{entity_id}",
        )
    start_point = content.initial_state.start_time_point_id
    if start_point is not None and start_point not in time_point_ids:
        issues.append(
            ValidationIssue(
                severity="error",
                code="MODULE_V3_TIME_POINT_NOT_FOUND",
                path="initial_state.start_time_point_id",
                message=f"引用了不存在的时间点: {start_point}",
            )
        )

    return issues


def _location_cycle_issues(content: ModuleContentV3) -> list[ValidationIssue]:
    """`parent_location_id` drives the UI breadcrumb, so it must be a forest.

    A cycle would make the breadcrumb walk forever; the self-loop case is already
    rejected by `LocationSpecV3`, but `a -> b -> a` needs the whole collection.
    """

    parents = {
        location.id: location.parent_location_id
        for location in content.locations
        if location.parent_location_id is not None
    }
    issues: list[ValidationIssue] = []
    reported: set[str] = set()
    for index, location in enumerate(content.locations):
        seen: set[str] = set()
        cursor: str | None = location.id
        while cursor is not None and cursor not in seen:
            seen.add(cursor)
            cursor = parents.get(cursor)
        if cursor is not None and cursor not in reported:
            reported |= seen
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="MODULE_V3_LOCATION_CYCLE",
                    path=f"locations.{index}.parent_location_id",
                    message=f"地点层级存在环: {' -> '.join(sorted(seen))}",
                )
            )
    return issues


def _condition_issues(condition: ConditionExpr, path: str) -> list[ValidationIssue]:
    """Reject empty logical nodes; a predicate's name is checked at load time."""

    if isinstance(condition, AllCondition | AnyCondition):
        issues: list[ValidationIssue] = []
        for index, item in enumerate(condition.items):
            issues.extend(_condition_issues(item, f"{path}.items.{index}"))
        return issues
    if isinstance(condition, NotCondition):
        return _condition_issues(condition.item, f"{path}.item")
    if isinstance(condition, PredicateCondition) and not condition.predicate.strip():
        return [
            ValidationIssue(
                severity="error",
                code="MODULE_V3_PREDICATE_EMPTY",
                path=f"{path}.predicate",
                message="predicate 名称不能为空",
            )
        ]
    return []


def _rule_issues(
    rule: RuleSpecV3,
    path: str,
    known: dict[str, set[str]],
    require,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if isinstance(rule.trigger, EventTriggerSpec):
        if rule.trigger.when is not None:
            issues.extend(_condition_issues(rule.trigger.when, f"{path}.trigger.when"))
    elif isinstance(rule.trigger, AgentMatchTriggerSpec):
        for index, location_id in enumerate(rule.trigger.scope.location_ids):
            require(
                location_id,
                "locations",
                "MODULE_V3_LOCATION_NOT_FOUND",
                f"{path}.trigger.scope.location_ids.{index}",
            )

    reachable = _reachable_steps(rule)
    for index, step in enumerate(rule.execution.steps):
        step_path = f"{path}.execution.steps.{index}"
        if step.id not in reachable:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="MODULE_V3_RULE_STEP_UNREACHABLE",
                    path=step_path,
                    message=f"步骤 {step.id} 从任何分支入口都到不了",
                )
            )
        if isinstance(step, EffectStep):
            issues.extend(_effect_issues(step, f"{step_path}.effect", known))
        elif isinstance(step, CreateNpcActionOpportunityStep):
            require(
                step.entity_id,
                "entities",
                "MODULE_V3_ENTITY_NOT_FOUND",
                f"{step_path}.entity_id",
            )
        elif isinstance(step, CheckStep | AdjudicatedCheckStep) and not step.result_routes:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="MODULE_V3_RULE_CHECK_UNROUTED",
                    path=f"{step_path}.result_routes",
                    message="检定步骤必须至少路由一个结果等级",
                )
            )

    if rule.presentation is not None:
        presentation_ids = {rule.presentation.id}
        for index, step in enumerate(rule.execution.steps):
            if (
                getattr(step, "kind", None) == "presentation"
                and step.presentation_id not in presentation_ids
            ):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="MODULE_V3_RULE_PRESENTATION_NOT_FOUND",
                        path=f"{path}.execution.steps.{index}.presentation_id",
                        message=f"引用了未声明的展示片段: {step.presentation_id}",
                    )
                )
    return issues


def _reachable_steps(rule: RuleSpecV3) -> set[str]:
    from collaboration_framework.contracts.module_v3 import _step_targets

    steps = {step.id: step for step in rule.execution.steps}
    reachable: set[str] = set()
    frontier = [branch.entry_step_id for branch in rule.execution.branches]
    while frontier:
        current = frontier.pop()
        if current in reachable or current not in steps:
            continue
        reachable.add(current)
        frontier.extend(_step_targets(steps[current]))
    return reachable


def _effect_issues(step: EffectStep, path: str, known: dict[str, set[str]]) -> list[ValidationIssue]:
    """Check the Canon ids an effect names.

    `ensure_runtime_*` effects deliberately name ids that must *not* exist yet,
    so they are skipped here — the Engine's Canon-shadow guard owns that at
    submit time (#212 §8.2).
    """

    effect = step.effect
    if getattr(effect, "type", "").startswith("ensure_runtime"):
        return []
    issues: list[ValidationIssue] = []
    for field, (collection, code) in _EFFECT_REFERENCES.items():
        value = getattr(effect, field, None)
        if isinstance(value, str) and value not in known[collection]:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code=code,
                    path=f"{path}.{field}",
                    message=f"效果引用了不存在的 {collection[:-1]}: {value}",
                )
            )
    return issues


__all__ = [
    "validate_module_v3",
    "validate_module_v3_json",
]
