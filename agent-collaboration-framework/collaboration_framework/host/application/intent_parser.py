"""Application-level Pydantic validation and trusted-candidate hardening."""

from collaboration_framework.contracts import (
    ContractError,
    Intent,
    MatchedTarget,
    ModuleCheck,
)
from collaboration_framework.host.ports import IntentModelPort
from collaboration_framework.host.schemas import IntentContext


class IntentParser:
    def __init__(self, model: IntentModelPort) -> None:
        self._model = model

    async def parse(self, context: IntentContext) -> Intent:
        raw = await self._model.generate(context)
        intent = Intent.model_validate(raw)
        return validate_intent_against_view(intent, context)


def validate_intent_against_view(
    intent: Intent,
    context: IntentContext,
) -> Intent:
    """Fail closed without replacing the Agent's semantic checkpoint choice."""

    if not isinstance(intent.target, MatchedTarget):
        return intent

    visible_ids = {item.id for item in context.player_view.visible_entities}
    if intent.target.id not in visible_ids:
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
    return intent
