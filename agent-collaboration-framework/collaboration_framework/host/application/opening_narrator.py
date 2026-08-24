"""Validation and deterministic fallback for the authoritative game opening."""

from __future__ import annotations

from typing import Literal

from collaboration_framework.contracts import ContractError
from collaboration_framework.host.ports import OpeningNarrationModelPort
from collaboration_framework.host.schemas import (
    NarrationOutput,
    OpeningNarrationContext,
)

from .narration_policy import (
    narration_subject_rejection_reason,
    narration_text_rejection_reason,
    normalize_narration_text,
)

OpeningRejectionReason = Literal[
    "outer_schema",
    "opening_contract",
    "participant_coverage",
    "protocol_tail",
    "schema_fragment",
    "subject_ownership",
]


class OpeningNarrationValidationError(ContractError):
    """Stable rejection category for an unsafe or malformed opening candidate."""

    def __init__(self, reason: OpeningRejectionReason) -> None:
        super().__init__("Opening NarrationOutput 未通过玩家可见输出安全校验")
        self.reason = reason


class OpeningNarrator:
    """Validate an untrusted provider candidate before it becomes player-visible."""

    def __init__(self, model: OpeningNarrationModelPort) -> None:
        self._model = model

    async def narrate(self, context: OpeningNarrationContext) -> NarrationOutput:
        """Require a narration-only result that names every public participant."""

        raw = await self._model.generate(context)
        if isinstance(raw, dict) and isinstance(raw.get("text"), str):
            raw = {**raw, "text": normalize_narration_text(raw["text"])}
        try:
            output = NarrationOutput.model_validate(raw)
        except (TypeError, ValueError) as exc:
            raise OpeningNarrationValidationError("outer_schema") from exc
        if (
            output.kind != "narration"
            or output.claimed_fact_ids
            or output.suggested_actions
        ):
            raise OpeningNarrationValidationError("opening_contract")
        rejection_reason = narration_text_rejection_reason(output.text)
        if rejection_reason is not None:
            raise OpeningNarrationValidationError(rejection_reason)
        subject_rejection = narration_subject_rejection_reason(
            output.text,
            addressing_mode=getattr(context, "addressing_mode", "second_person"),
        )
        if subject_rejection is not None:
            raise OpeningNarrationValidationError("subject_ownership")
        if any(
            participant.name not in output.text for participant in context.participants
        ):
            raise OpeningNarrationValidationError("participant_coverage")
        return output


def deterministic_opening_narration(
    context: OpeningNarrationContext,
) -> NarrationOutput:
    """Build a public, deterministic opening without exposing private actor data."""

    addressing_mode = getattr(context, "addressing_mode", "second_person")
    scene_name = context.scene.name.strip()
    scene_description = context.scene.description.strip()
    if scene_description and narration_subject_rejection_reason(
        scene_description,
        addressing_mode=addressing_mode,
    ):
        # 模组可见描述可能含未加引号的「你」；named_actor 下整段丢掉，不改写原文。
        scene_description = ""
    scene_lines = [line for line in (scene_name, scene_description) if line]
    participant_labels = []
    for participant in context.participants:
        public_details = [
            detail
            for detail in (participant.occupation, participant.status_summary)
            if detail and detail.strip()
        ]
        label = participant.name
        if public_details:
            label = f"{label}（{'，'.join(public_details)}）"
        participant_labels.append(label)
    if len(participant_labels) == 1:
        scene_lines.append(f"{participant_labels[0]}此刻就在这里。")
    else:
        scene_lines.append(f"共同在场的调查员有：{'、'.join(participant_labels)}。")
    return NarrationOutput(
        kind="narration",
        text="\n".join(scene_lines),
        claimed_fact_ids=(),
        suggested_actions=(),
    )
