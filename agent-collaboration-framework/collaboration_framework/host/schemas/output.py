"""Player-visible narration output shared by active Host flows."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from collaboration_framework.contracts import ContractModel


class NarrationOutput(ContractModel):
    kind: Literal["narration", "clarification"] = "narration"
    text: str = Field(min_length=1)
    claimed_fact_ids: tuple[str, ...] = ()
    suggested_actions: tuple[str, ...] = ()
