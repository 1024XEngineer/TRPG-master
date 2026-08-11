"""Grounded ending draft and confirmation contracts (#212 section 10)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, JsonValue, model_validator

from .common import ContractModel


class CreateEndingDraftRequest(ContractModel):
    request_id: str = Field(min_length=1, max_length=200)
    source_revision: str = Field(min_length=1)
    mode: Literal["ending_and_epilogue"] = "ending_and_epilogue"
    player_intent: str = Field(min_length=1, max_length=1000)


class EndingDraft(ContractModel):
    draft_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    mode: Literal["ending_and_epilogue"] = "ending_and_epilogue"
    player_intent: str = Field(min_length=1)
    title: str = Field(min_length=1, max_length=300)
    summary: str = Field(min_length=1)
    epilogue: str = Field(min_length=1)
    facets: dict[str, JsonValue] = Field(default_factory=dict)
    evidence_refs: tuple[str, ...] = Field(min_length=1)
    version: int = Field(default=1, ge=1)
    status: Literal["active", "confirmed", "expired"] = "active"

    @model_validator(mode="after")
    def validate_evidence(self) -> EndingDraft:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("EndingDraft evidence_refs 必须唯一")
        return self


class ConfirmEndingDraftRequest(ContractModel):
    request_id: str = Field(min_length=1, max_length=200)
    source_revision: str = Field(min_length=1)
    draft_version: int = Field(ge=1)


class EndingResolution(ContractModel):
    draft_id: str = Field(min_length=1)
    source_revision: str = Field(min_length=1)
    anchor_id: str = Field(min_length=1)
    fact_refs: tuple[str, ...] = Field(min_length=1)
    facets: dict[str, JsonValue] = Field(default_factory=dict)
    confirmed_by: str = Field(min_length=1)
    confirmed_event_id: str = Field(min_length=1)


class ConfirmEndingDraftResult(ContractModel):
    request_id: str = Field(min_length=1)
    resolution: EndingResolution
    revision: str = Field(min_length=1)


__all__ = [
    "ConfirmEndingDraftRequest",
    "ConfirmEndingDraftResult",
    "CreateEndingDraftRequest",
    "EndingDraft",
    "EndingResolution",
]
