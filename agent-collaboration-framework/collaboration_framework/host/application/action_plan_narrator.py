"""Validate one player-visible narration over committed ActionPlan evidence."""

from __future__ import annotations

from collaboration_framework.contracts import ContractError
from collaboration_framework.host.ports.action_plan import ActionPlanNarrationModelPort
from collaboration_framework.host.schemas.action_plan import (
    ActionPlanNarrationContext,
    ActionPlanNarrationOutput,
)

from .narrator import (
    narration_subject_rejection_reason,
    narration_text_rejection_reason,
    normalize_narration_text,
)


class ActionPlanNarrationValidationError(ContractError):
    def __init__(self, reason: str) -> None:
        super().__init__("ActionPlanNarrationOutput 未通过玩家可见输出安全校验")
        self.reason = reason


class ActionPlanNarrator:
    def __init__(self, model: ActionPlanNarrationModelPort) -> None:
        self._model = model

    async def narrate(
        self,
        context: ActionPlanNarrationContext,
    ) -> ActionPlanNarrationOutput:
        raw = await self._model.generate(context)
        if isinstance(raw, dict) and isinstance(raw.get("text"), str):
            raw = {**raw, "text": normalize_narration_text(raw["text"])}
        try:
            output = ActionPlanNarrationOutput.model_validate(raw)
        except (TypeError, ValueError) as exc:
            raise ActionPlanNarrationValidationError("outer_schema") from exc
        if not set(output.claimed_evidence_refs).issubset(
            context.allowed_evidence_refs
        ):
            raise ActionPlanNarrationValidationError("evidence_scope")
        rejection = narration_text_rejection_reason(output.text)
        if rejection is not None:
            raise ActionPlanNarrationValidationError(rejection)
        subject_rejection = narration_subject_rejection_reason(output.text)
        if subject_rejection is not None:
            raise ActionPlanNarrationValidationError(subject_rejection)
        if context.termination_status == "needs_clarification" and output.kind != "clarification":
            raise ActionPlanNarrationValidationError("clarification_kind")
        return output
