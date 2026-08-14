"""Validate one player-visible narration over committed ActionPlan evidence."""

from __future__ import annotations

import re

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
from .persistent_results import (
    unsupported_inventory_acquisition_claim,
    unsupported_persistent_claim,
)


class ActionPlanNarrationValidationError(ContractError):
    def __init__(self, reason: str) -> None:
        super().__init__("ActionPlanNarrationOutput 未通过玩家可见输出安全校验")
        self.reason = reason


_CORPSE_SEARCH_QUESTION = re.compile(
    r"(?:从哪里|哪里).{0,12}(?:找|搜)|(?:寻找|搜寻).{0,12}(?:尸体|遗体)"
)


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
        required = tuple(
            item for item in context.narration_evidence if item.required_in_narration
        )
        mentioned_required = tuple(
            item
            for item in required
            if any(
                label and label in output.text
                for label in (item.subject_name, *item.subject_aliases)
            )
        )
        if len(mentioned_required) != len(required):
            raise ActionPlanNarrationValidationError("required_evidence_missing")
        # The prose is the player-facing source of truth. Once it demonstrably
        # reports a required safe result, record its public ref deterministically
        # instead of discarding otherwise valid narration because the model
        # omitted a bookkeeping field.
        claimed = tuple(
            dict.fromkeys(
                (*output.claimed_evidence_refs, *(item.ref for item in mentioned_required))
            )
        )
        if claimed != output.claimed_evidence_refs:
            output = output.model_copy(update={"claimed_evidence_refs": claimed})
        rejection = narration_text_rejection_reason(output.text)
        if rejection is not None:
            raise ActionPlanNarrationValidationError(rejection)
        subject_rejection = narration_subject_rejection_reason(output.text)
        if subject_rejection is not None:
            raise ActionPlanNarrationValidationError(subject_rejection)
        committed_results = tuple(
            result
            for step in context.completed_steps
            for result in step.committed_results
        )
        persistent_rejection = unsupported_persistent_claim(
            output.text,
            committed_results,
            context.player_view,
        )
        if persistent_rejection is not None:
            raise ActionPlanNarrationValidationError(
                f"persistent_claim_without_evidence:{persistent_rejection}"
            )
        inventory_rejection = unsupported_inventory_acquisition_claim(
            output.text,
            committed_results,
            context.player_view,
        )
        if inventory_rejection is not None:
            raise ActionPlanNarrationValidationError(
                f"persistent_claim_without_evidence:{inventory_rejection}"
            )
        visible_dead = tuple(
            entity
            for entity in context.player_view.scene.visible_entities
            if any(
                state.key == "consciousness" and state.value == "dead"
                for state in entity.observable_state
            )
        )
        if (
            visible_dead
            and any(word in context.player_input.utterance for word in ("尸体", "遗体"))
            and _CORPSE_SEARCH_QUESTION.search(output.text)
        ):
            # PlayerView 已确认尸体就在当前场景时，不能反问玩家去哪里寻找；
            # 这会把权威可见状态重新降级成模型猜测。
            raise ActionPlanNarrationValidationError("visible_corpse_search_conflict")
        if (
            context.termination_status == "needs_clarification"
            and output.kind != "clarification"
        ):
            raise ActionPlanNarrationValidationError("clarification_kind")
        return output
