"""Runtime capability audit for published ModuleContent."""

from __future__ import annotations

from pydantic import Field

from collaboration_framework.contracts import (
    ContractError,
    ContractModel,
    ModuleContentV3,
)
from collaboration_framework.registry import rulesets as ruleset_registry

SUPPORTED_WORLD_REFS = ruleset_registry.DEFAULT_RULESET_REGISTRY.world_refs


class RuntimeCapabilityIssue(ContractModel):
    owner: str = Field(min_length=1)
    capability: str = Field(min_length=1)
    message: str = Field(min_length=1)


def audit_runtime_capabilities(
    module_content: ModuleContentV3,
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

    if ruleset_registry.is_registered(module_content.world_ref):
        return ()
    return (
        RuntimeCapabilityIssue(
            owner=f"module:{module_content.module_id}",
            capability=f"world_ref:{module_content.world_ref}",
            message=("The deterministic runtime has no ruleset resolver for this world."),
        ),
    )


def require_runtime_capabilities(
    module_content: ModuleContentV3,
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
