"""Deterministic adjudication validation and internal authority diagnostics.

The authority level is an output of the B-owned validator.  It deliberately
does not appear in any action request or player-facing execution model.
"""

from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import Field, model_validator

from .common import ContractError, ContractModel

AuthorityLevel: TypeAlias = Literal["L0", "L1", "L2", "L3", "L4", "L5"]
ValidationStatus: TypeAlias = Literal["accepted", "rejected"]
Repairability: TypeAlias = Literal[
    "auto_repairable",
    "retry_with_latest_revision",
    "requires_player_choice",
    "hard_reject",
]
ValidationFault: TypeAlias = Literal["agent", "player", "engine"]
ClassificationCoverage: TypeAlias = Literal[
    "complete",
    "partial_validation_failure",
    "rule_effects_excluded",
    "legacy_unknown",
]
EffectApplicationStatus: TypeAlias = Literal[
    "not_applied",
    "not_selected",
    "applied",
    "partial",
]
ValidationBranch: TypeAlias = Literal["success", "failure", "selected"]


class SafeEffectRef(ContractModel):
    """A non-sensitive effect location for A/Host repair feedback."""

    branch: ValidationBranch
    effect_index: int = Field(ge=0)
    effect_type: str = Field(min_length=1)


class EffectValidationDetail(ContractModel):
    """Internal per-effect classification and eventual application state."""

    branch: ValidationBranch
    effect_index: int = Field(ge=0)
    effect_type: str = Field(min_length=1)
    authority_level: AuthorityLevel
    application_status: EffectApplicationStatus = "not_applied"
    target_ref: str | None = Field(default=None, min_length=1)
    evidence_refs: tuple[str, ...] = ()


class ValidationResult(ContractModel):
    """Complete B-side result; this model is never serialized to PlayerView."""

    status: ValidationStatus
    authority_level: AuthorityLevel | None = None
    code: str = Field(min_length=1, max_length=100)
    repairability: Repairability | None = None
    fault: ValidationFault | None = None
    player_safe_reason: str = Field(min_length=1, max_length=512)
    affected_effects: tuple[EffectValidationDetail, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    classification_coverage: ClassificationCoverage = "complete"
    internal_reason: str | None = Field(default=None, max_length=1024)

    @model_validator(mode="after")
    def validate_shape(self) -> ValidationResult:
        if self.status == "accepted":
            if (
                self.code != "OK"
                or self.repairability is not None
                or self.fault is not None
            ):
                raise ValueError(
                    "accepted 校验结果必须使用 OK 且不包含 repairability/fault"
                )
        elif self.repairability is None or self.fault is None:
            raise ValueError("rejected 校验结果必须包含 repairability 和 fault")
        return self

    def to_feedback(self) -> ValidationFeedback:
        """Project the result without authority, target evidence, or GM detail."""

        public_code = {
            "TARGET_NOT_FOUND": "TARGET_UNAVAILABLE",
            "CANON_SHADOW": "TARGET_UNAVAILABLE",
            "RULE_BUDGET_EXCEEDED": "RULE_ENGINE_UNAVAILABLE",
        }.get(self.code, self.code)
        return ValidationFeedback(
            status=self.status,
            code=public_code,
            repairability=self.repairability,
            fault=self.fault,
            player_safe_reason=self.player_safe_reason,
            affected_effects=tuple(
                SafeEffectRef(
                    branch=item.branch,
                    effect_index=item.effect_index,
                    effect_type=item.effect_type,
                )
                for item in self.affected_effects
            ),
        )


class ValidationFeedback(ContractModel):
    """Safe projection consumed by A/Host and suitable for player messaging."""

    status: ValidationStatus
    code: str = Field(min_length=1, max_length=100)
    repairability: Repairability | None = None
    fault: ValidationFault | None = None
    player_safe_reason: str = Field(min_length=1, max_length=512)
    affected_effects: tuple[SafeEffectRef, ...] = ()


class AdjudicationValidationError(ContractError):
    """Typed rejection raised before an adjudication authoritative commit."""

    def __init__(self, result: ValidationResult) -> None:
        if result.status != "rejected":
            raise ValueError("AdjudicationValidationError 只能携带 rejected 结果")
        super().__init__(result.internal_reason or result.player_safe_reason)
        self.result = result
