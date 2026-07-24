"""Application-level validation for player-visible narration."""

from collaboration_framework.contracts import ContractError
from collaboration_framework.host.ports import NarrationModelPort
from collaboration_framework.host.schemas import NarrationContext, NarrationOutput


class Narrator:
    def __init__(self, model: NarrationModelPort) -> None:
        self._model = model

    async def narrate(self, context: NarrationContext) -> NarrationOutput:
        raw = await self._model.generate(context)
        output = NarrationOutput.model_validate(raw)
        allowed = {fact.id for fact in context.action_result.visible_facts}
        if not set(output.claimed_fact_ids).issubset(allowed):
            raise ContractError("NarrationOutput 引用了未确认的玩家可见事实")
        return output
