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
    InvokeRulesetActionStep,
    ModuleContentV3,
    NotCondition,
    PredicateCondition,
    RuleSpecV3,
    RuleStepSpec,
)
from collaboration_framework.registry import effects as effect_registry
from collaboration_framework.registry import predicates as predicate_registry
from collaboration_framework.registry import rule_steps as rule_step_registry
from collaboration_framework.registry import rulesets as ruleset_registry

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
        issues.extend(_accompanying_issues(entity.state, f"entities.{index}.state"))
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
        issues.extend(
            _rule_issues(rule, f"rules.{index}", known, require, content.world_ref)
        )

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
        issues.extend(
            _accompanying_issues(
                content.initial_state.entity_state[entity_id],
                f"initial_state.entity_state.{entity_id}",
            )
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


def _accompanying_value_issues(value: Any, path: str) -> list[ValidationIssue]:
    """`accompanying` 是引擎保留键，只接受布尔值（#516）。

    引擎把移动语义挂在了这个键上：为 True 的实体在队伍换场景时被一并带走。写成
    `"yes"` 之类的真值字符串在结构上完全合法，运行时却永远等不到那个 `is True`
    ——随行静默失效，和这个键存在之前没有区别。这正是 #347 要求登记表在发布期拦下
    的那一类问题：引擎认识这个名字但内容写错了，发布期报错，而不是运行期无声地
    什么都不做。
    """

    if isinstance(value, bool):
        return []
    key = effect_registry.ACCOMPANYING_STATE_KEY
    return [
        ValidationIssue(
            severity="error",
            code="MODULE_V3_ACCOMPANYING_NOT_BOOLEAN",
            path=path,
            message=f"引擎保留键 {key} 只接受布尔值: {value!r}",
        )
    ]


def _accompanying_issues(values: dict[str, Any], path: str) -> list[ValidationIssue]:
    """检查一份实体状态声明里的 `accompanying` 初始值。"""

    key = effect_registry.ACCOMPANYING_STATE_KEY
    if key not in values:
        return []
    return _accompanying_value_issues(values[key], f"{path}.{key}")


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
    """Reject empty or unregistered predicate names (#347 Phase 1).

    The predicate *name* is now checked against `registry/predicates.py` —
    the one deliberate, called-out behaviour change in issue #347's otherwise
    pure-refactor scope: a typo'd or made-up predicate name used to pass
    publish and just silently never fire at runtime
    (`_UNKNOWN_PREDICATE_IS_FALSE`); it is now rejected here instead, with the
    rule pinpointed. Argument *shape* is deliberately still not checked here
    (see `registry/predicates.py` module docstring) — only the name.
    """

    if isinstance(condition, AllCondition | AnyCondition):
        issues: list[ValidationIssue] = []
        for index, item in enumerate(condition.items):
            issues.extend(_condition_issues(item, f"{path}.items.{index}"))
        return issues
    if isinstance(condition, NotCondition):
        return _condition_issues(condition.item, f"{path}.item")
    if isinstance(condition, PredicateCondition):
        if not condition.predicate.strip():
            return [
                ValidationIssue(
                    severity="error",
                    code="MODULE_V3_PREDICATE_EMPTY",
                    path=f"{path}.predicate",
                    message="predicate 名称不能为空",
                )
            ]
        if not predicate_registry.is_registered(condition.predicate):
            return [
                ValidationIssue(
                    severity="error",
                    code="MODULE_V3_PREDICATE_UNKNOWN",
                    path=f"{path}.predicate",
                    message=f"引用了未注册的 predicate: {condition.predicate}",
                )
            ]
    return []


def _rule_issues(
    rule: RuleSpecV3,
    path: str,
    known: dict[str, set[str]],
    require,
    world_ref: str,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if isinstance(rule.trigger, EventTriggerSpec):
        if rule.trigger.when is not None:
            issues.extend(_condition_issues(rule.trigger.when, f"{path}.trigger.when"))
    elif isinstance(rule.trigger, AgentMatchTriggerSpec):
        if rule.trigger.when is not None:
            issues.extend(_condition_issues(rule.trigger.when, f"{path}.trigger.when"))
        issues.extend(_agent_match_hint_issues(rule.trigger, f"{path}.trigger"))
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
        issues.extend(_actor_binding_issues(step, step_path))
        issues.extend(_check_profile_issues(step, step_path, world_ref))

    # 这里曾校验 `presentation` step 的 `presentation_id` 指向 `rule.presentation`
    # 声明过的片段。随 `RulePresentationSpec` 一起删除（#288 结案、#398 执行）：
    # 被引用的一侧不存在了，这条检查也就无从谈起。`PresentationStep` 仍在 union
    # 里但依旧不接通，两个已发布模组都没有用过它。
    return issues


def _agent_match_hint_issues(
    trigger: AgentMatchTriggerSpec,
    path: str,
) -> list[ValidationIssue]:
    """Reject machine identifiers masquerading as semantic Match hints.

    该函数只校验模型看到的规则问题提示词，不改变 action_family 的运行时开放性。
    ``semantic_hints`` is the model-facing natural-language vocabulary. Family
    names and option ids remain valid contract fields, but copying them into the
    hint list makes the published vocabulary less useful and can hide duplicate
    entries. Comparisons are normalized only for validation; diagnostics retain
    the authored array index.
    """

    def normalize(value: str) -> str:
        return value.strip().casefold()

    families = {normalize(value) for value in trigger.scope.action_families}
    option_ids = {normalize(option.id) for option in trigger.options}
    issues: list[ValidationIssue] = []
    seen: dict[str, int] = {}
    for index, hint in enumerate(trigger.question.semantic_hints):
        hint_path = f"{path}.question.semantic_hints.{index}"
        normalized = normalize(hint)
        if normalized in families:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="MODULE_V3_AGENT_MATCH_HINT_EQUALS_ACTION_FAMILY",
                    path=hint_path,
                    message="semantic_hint 不能直接等于 action_family",
                )
            )
        if normalized in option_ids:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="MODULE_V3_AGENT_MATCH_HINT_EQUALS_OPTION_ID",
                    path=hint_path,
                    message="semantic_hint 不能直接等于 option id",
                )
            )
        if normalized in seen:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="MODULE_V3_AGENT_MATCH_HINT_DUPLICATE",
                    path=hint_path,
                    message=f"semantic_hint 与第 {seen[normalized]} 项重复",
                )
            )
        else:
            seen[normalized] = index
    return issues


def _actor_binding_issues(step: RuleStepSpec, step_path: str) -> list[ValidationIssue]:
    """Check `actor_binding` against the registered value space (#347 §4.8).

    Nothing reads this field yet — resolving a binding into actual actors is a
    later issue. Registering the value space and rejecting anything outside it
    is the whole of what this phase does with it, per #347 §4.7's
    "migrate and load completely, do not implement".
    """

    if isinstance(step, CheckStep):
        binding, path = step.check.actor_binding, f"{step_path}.check.actor_binding"
    elif isinstance(step, InvokeRulesetActionStep):
        binding, path = step.actor_binding, f"{step_path}.actor_binding"
    else:
        return []
    if rule_step_registry.is_registered_actor_binding(binding):
        return []
    return [
        ValidationIssue(
            severity="error",
            code="MODULE_V3_ACTOR_BINDING_UNKNOWN",
            path=path,
            message=f"引用了未注册的 actor_binding: {binding}",
        )
    ]


def _check_profile_issues(
    step: RuleStepSpec,
    step_path: str,
    world_ref: str,
) -> list[ValidationIssue]:
    """被动检定的 `profile_id` 必须在对应 world adapter 里注册过。

    只校验 `initiation_kind == "passive_rule"`，这是刻意收窄，不是遗漏。主动检定
    的 `profile_id` 走的是 Agent 候选菜单，压根不经过这张表——两个线上模组的 26
    处主动检定全写着 `coc7.skill`，而 `coc7.skill` 按设计**不**在表里。不收窄的
    话这条校验会当场拒掉全部已发布内容。

    被动检定不一样：引擎必须自己把 `profile_id` 译成「掷什么、对多少」，译不出来
    就只能在运行时 `settlement.fail("check_profile_unavailable")`——那时效果已经
    提交了一半。同样一件事，发布期说比运行时说好。这也让
    规则系统 adapter 的 Profile 注册表有了真实消费者。
    """

    if not isinstance(step, CheckStep) or step.check.initiation_kind != "passive_rule":
        return []
    if ruleset_registry.check_profile_for(world_ref, step.check.profile_id) is not None:
        return []
    return [
        ValidationIssue(
            severity="error",
            code="MODULE_V3_CHECK_PROFILE_NOT_REGISTERED",
            path=f"{step_path}.check.profile_id",
            message=f"被动检定引用了未注册的 check profile: {step.check.profile_id}",
        )
    ]


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
    if getattr(effect, "type", "") == "commit_terminal_ending":
        return [
            ValidationIssue(
                severity="error",
                code="MODULE_V3_DIRECT_ENDING_FORBIDDEN",
                path=f"{path}.type",
                message="v3 终局必须通过 EndingDraft 审阅与确认 API 提交",
            )
        ]
    if getattr(effect, "type", "").startswith("ensure_runtime"):
        return []
    issues: list[ValidationIssue] = []
    if getattr(effect, "key", None) == effect_registry.ACCOMPANYING_STATE_KEY:
        issues.extend(
            _accompanying_value_issues(getattr(effect, "value", None), f"{path}.value")
        )
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
