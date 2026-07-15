"""Deterministic hardening for model-proposed execution and check routes."""

from __future__ import annotations

from .contracts import (
    ContractError,
    Intent,
    MatchedTarget,
    ModuleCheck,
    TurnContext,
)


def harden_intent_routing(intent: Intent, context: TurnContext) -> Intent:
    """Return a fail-closed route derived from trusted turn context.

    ``Intent.execution`` and ``Intent.check`` remain model proposals.  A matched
    action may bypass the atomic engine only when ContextAssembler explicitly
    exposes it in ``VisibleEntity.narrative_actions``.
    """

    if intent.kind == "unknown":
        return intent
    if not isinstance(intent.target, MatchedTarget):
        raise ContractError("可执行 Intent 缺少已匹配目标")

    entity = next(
        (item for item in context.visible_entities if item.id == intent.target.id),
        None,
    )
    if entity is None:
        raise ContractError("Intent target 不在当前可见候选中")

    matching_checkpoints = [
        item
        for item in context.checkpoint_options
        if item.action == intent.action and item.target_id == intent.target.id
    ]
    if isinstance(intent.check, ModuleCheck):
        if not any(
            item.id == intent.check.checkpoint_id for item in matching_checkpoints
        ):
            raise ContractError("Intent checkpoint 与当前 action/target 不匹配")
        return intent.model_copy(update={"execution": "engine"})

    if matching_checkpoints:
        if len(matching_checkpoints) != 1:
            raise ContractError(
                "当前 action/target 命中多个 Checkpoint，无法唯一硬化"
            )
        checkpoint = matching_checkpoints[0]
        return intent.model_copy(
            update={
                "execution": "engine",
                "check": ModuleCheck(
                    checkpoint_id=checkpoint.id,
                    proposed_skills=checkpoint.skills,
                ),
            }
        )

    if (
        intent.execution == "narrative"
        and intent.action not in entity.narrative_actions
    ):
        return intent.model_copy(update={"execution": "engine"})
    return intent
