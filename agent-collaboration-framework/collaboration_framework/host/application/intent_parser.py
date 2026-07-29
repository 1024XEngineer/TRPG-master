"""Deterministic validation boundary for untrusted Host Agent output."""

from collaboration_framework.contracts import (
    ContractError,
    DefaultCheck,
    Intent,
    JsonObject,
    MatchedTarget,
    ModuleCheck,
)
from collaboration_framework.host.schemas import IntentContext

from .intent_aligner import align_intent_for_engine


class IntentParser:
    """Parse one raw JSON object without invoking a model or mutating state."""

    @staticmethod
    def parse(raw: JsonObject, context: IntentContext) -> Intent:
        intent = Intent.model_validate(raw)
        validated = validate_intent_against_view(intent, context)
        return align_intent_for_engine(validated, context)


def validate_intent_against_view(
    intent: Intent,
    context: IntentContext,
) -> Intent:
    """Fail closed without replacing the Agent's semantic checkpoint choice."""

    if not isinstance(intent.target, MatchedTarget):
        return intent

    visible_entity_ids = {
        item.id for item in context.player_view.scene.visible_entities
    }
    available_exit_ids = {item.id for item in context.player_view.scene.available_exits}
    trusted_target_ids = visible_entity_ids | available_exit_ids
    if isinstance(intent.check, DefaultCheck):
        # Environment-wide perception and movement checks do not always have a
        # concrete Entity target.  The current player-safe Scene is the trusted
        # target for actions such as looking around, listening, or hiding.
        trusted_target_ids.add(context.player_view.scene.id)
    if intent.target.id not in trusted_target_ids:
        raise ContractError("Intent target 不在当前 PlayerView 中")

    if isinstance(intent.check, ModuleCheck):
        option = next(
            (
                item
                for item in context.player_view.checkpoint_options
                if item.id == intent.check.checkpoint_id
            ),
            None,
        )
        if option is None:
            raise ContractError("Intent checkpoint 不在可信候选中")
        if option.target_id != intent.target.id:
            raise ContractError("Intent checkpoint 与目标不一致")
        if not set(intent.check.proposed_skills).issubset(option.skills):
            raise ContractError("Intent proposed_skills 不属于 Checkpoint 候选技能")
    elif isinstance(intent.check, DefaultCheck):
        if not intent.check.proposed_skills:
            raise ContractError("Default Check 至少需要一个候选属性或技能")
        actor_candidates = _actor_check_candidates(context)
        if not set(intent.check.proposed_skills).issubset(actor_candidates):
            raise ContractError(
                "Default Check 只能使用当前 Actor 的整数属性、技能或 luck"
            )
    return intent


def _actor_check_candidates(context: IntentContext) -> set[str]:
    candidates = {
        item.id
        for item in (
            *context.player_view.self_actor.attributes,
            *context.player_view.self_actor.skills,
        )
        if isinstance(item.value, int) and not isinstance(item.value, bool)
    }
    candidates.update(
        item.id
        for item in context.player_view.self_actor.resources
        if item.id == "luck"
        and isinstance(item.value, int)
        and not isinstance(item.value, bool)
    )
    return candidates
