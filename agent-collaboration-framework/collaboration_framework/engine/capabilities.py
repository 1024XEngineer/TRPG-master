"""Runtime capability audit for published ModuleContent."""

from __future__ import annotations

from pydantic import Field

from collaboration_framework.contracts import (
    ContractError,
    ContractModel,
    ForceOperationSpec,
    ModuleContent,
    ModuleContentV3,
    OperationSpec,
)

from .expression import ExpressionEvaluator

SUPPORTED_WORLD_REFS = frozenset({"coc-7e"})
SUPPORTED_HOOKS = frozenset(
    {
        "on_attack_declare",
        "on_check_declare",
        "on_check_roll",
        "on_check_resolve",
        "on_scene_enter",
        "on_scene_exit",
        "on_interact",
        "on_state_change",
        "on_time_elapsed",
        "on_death",
        "on_turn_end",
    }
)
SUPPORTED_OPERATIONS = frozenset(
    {
        "allow",
        "modify",
        "set",
        "add",
        "forbid",
        "force",
        "apply_condition",
        "trigger_ending",
        "trigger_rule",
        "transition",
    }
)
_SUPPORTED_FORCE_PREFIXES = (
    "coc7.san_check(",
    "coc7.san_loss(",
    "coc7.san_gain(",
    "coc7.gain_mythos(",
)
_SUPPORTED_FORCE_ACTIONS = frozenset({"ghouls_overwhelm_and_abduct_actor"})


class RuntimeCapabilityIssue(ContractModel):
    owner: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    message: str = Field(min_length=1)


def audit_runtime_capabilities(
    module_content: ModuleContent | ModuleContentV3,
) -> tuple[RuntimeCapabilityIssue, ...]:
    """Refuse to run a module whose declared capabilities the runtime lacks.

    v3 needs a much shorter audit than v2: hooks and free-form operations are
    gone, and a v3 Rule can only reference registered Steps, Effects and
    Predicates (#226 §1). Steps and Effects are enforced by their discriminated
    unions in `contracts/module_v3.py`; Predicate *names* are enforced at
    publish time by `module/validation_v3.py` against
    `engine/registry/predicates.py` (#347). Until that registry existed this
    docstring overstated the guarantee — an unregistered predicate name passed
    every static check and only ever read false at runtime. What is left to
    check here at load time is the world ruleset.
    """

    if isinstance(module_content, ModuleContentV3):
        if module_content.world_ref in SUPPORTED_WORLD_REFS:
            return ()
        return (
            RuntimeCapabilityIssue(
                owner=f"module:{module_content.module_id}",
                capability=f"world_ref:{module_content.world_ref}",
                message=(
                    "The deterministic runtime has no ruleset resolver for this world."
                ),
            ),
        )
    issues: list[RuntimeCapabilityIssue] = []
    if module_content.world_ref not in SUPPORTED_WORLD_REFS:
        issues.append(
            RuntimeCapabilityIssue(
                owner=f"module:{module_content.module_id}",
                capability=f"world_ref:{module_content.world_ref}",
                message=(
                    "The deterministic runtime has no ruleset resolver for this world."
                ),
            )
        )
    rules = [
        *module_content.module_rules,
        *(rule for entity in module_content.entities for rule in entity.rules),
    ]
    for rule in rules:
        if rule.hook not in SUPPORTED_HOOKS:
            issues.append(
                RuntimeCapabilityIssue(
                    owner=f"rule:{rule.id}",
                    capability=f"hook:{rule.hook}",
                    message="The deterministic runtime does not dispatch this hook.",
                )
            )
        issues.extend(_operation_issues(f"rule:{rule.id}", rule.then))
        if rule.when.expr is not None:
            issues.extend(_expression_issues(f"rule:{rule.id}", rule.when.expr))
    for checkpoint in module_content.checkpoints:
        if (
            checkpoint.visibility is not None
            and checkpoint.visibility.discovery_rule is not None
        ):
            issues.extend(
                _expression_issues(
                    f"checkpoint:{checkpoint.id}:visibility",
                    checkpoint.visibility.discovery_rule,
                )
            )
        for outcome_name, checkpoint_outcome in checkpoint.outcomes:
            if checkpoint_outcome is not None:
                issues.extend(
                    _operation_issues(
                        f"checkpoint:{checkpoint.id}:{outcome_name}",
                        checkpoint_outcome.ops,
                    )
                )
    for scene in module_content.scenes:
        for detail in scene.narrative_details:
            issues.extend(
                _visibility_issues(
                    f"scene:{scene.id}:detail:{detail.id}",
                    detail.visibility.discovery_rule,
                )
            )
        for available_exit in scene.available_exits:
            issues.extend(
                _visibility_issues(
                    f"scene:{scene.id}:exit:{available_exit.id}",
                    available_exit.visibility.discovery_rule,
                )
            )
    for entity in module_content.entities:
        issues.extend(
            _visibility_issues(
                f"entity:{entity.id}:visibility",
                entity.visibility.discovery_rule,
            )
        )
        for detail in entity.narrative_details:
            issues.extend(
                _visibility_issues(
                    f"entity:{entity.id}:detail:{detail.id}",
                    detail.visibility.discovery_rule,
                )
            )
        for observable in entity.observable_state:
            issues.extend(
                _visibility_issues(
                    f"entity:{entity.id}:state:{observable.key}",
                    observable.visibility.discovery_rule,
                )
            )
    for win_condition in module_content.win_conditions:
        if win_condition.when.expr is not None:
            issues.extend(
                _expression_issues(
                    f"win_condition:{win_condition.id}",
                    win_condition.when.expr,
                )
            )
    return tuple(issues)


def require_runtime_capabilities(
    module_content: ModuleContent | ModuleContentV3,
) -> None:
    issues = audit_runtime_capabilities(module_content)
    if not issues:
        return
    rendered = "; ".join(
        f"{issue.owner} -> {issue.capability}: {issue.message}" for issue in issues
    )
    raise ContractError(
        f"ModuleContent requires unsupported runtime capabilities: {rendered}"
    )


def _operation_issues(
    owner: str,
    operations: tuple[OperationSpec, ...],
) -> list[RuntimeCapabilityIssue]:
    issues: list[RuntimeCapabilityIssue] = []
    for operation in operations:
        if operation.op not in SUPPORTED_OPERATIONS:
            issues.append(
                RuntimeCapabilityIssue(
                    owner=owner,
                    capability=f"operation:{operation.op}",
                    message=(
                        "The deterministic runtime does not execute this operation."
                    ),
                )
            )
        elif isinstance(operation, ForceOperationSpec) and not _supports_force(
            operation.action
        ):
            issues.append(
                RuntimeCapabilityIssue(
                    owner=owner,
                    capability=f"force:{operation.action}",
                    message="The force action is not registered by the runtime.",
                )
            )
    return issues


def _supports_force(action: str) -> bool:
    return action in _SUPPORTED_FORCE_ACTIONS or action.startswith(
        _SUPPORTED_FORCE_PREFIXES
    )


def _expression_issues(
    owner: str,
    expression: str,
) -> list[RuntimeCapabilityIssue]:
    try:
        ExpressionEvaluator().validate(expression)
    except ContractError as exc:
        return [
            RuntimeCapabilityIssue(
                owner=owner,
                capability=f"expression:{expression}",
                message=str(exc),
            )
        ]
    return []


def _visibility_issues(
    owner: str,
    expression: str | None,
) -> list[RuntimeCapabilityIssue]:
    return _expression_issues(owner, expression) if expression is not None else []
