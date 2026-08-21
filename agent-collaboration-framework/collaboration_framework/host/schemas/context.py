"""Host-only model contexts; never imported by the engine or module parser."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from collaboration_framework.contracts import (
    ContractModel,
    NarrativeDetailView,
)


class OpeningSceneContext(ContractModel):
    """Only the player-visible portion of the initial shared scene."""

    id: str = Field(min_length=1)
    name: str
    description: str
    time: str | None = None
    narrative_details: tuple[NarrativeDetailView, ...] = ()


class OpeningParticipant(ContractModel):
    """Public identity and status allowed in the shared opening narration."""

    actor_id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    occupation: str | None = None
    status_summary: str = ""


class OpeningNarrationContext(ContractModel):
    """Player-safe context for one authoritative public game opening."""

    background: str = Field(
        min_length=1,
        description="玩家可知的时代、地点、故事前提与叙事基调。",
    )
    scene: OpeningSceneContext
    participants: tuple[OpeningParticipant, ...] = Field(min_length=1)
    solo_background_summary: str = ""
    addressing_mode: Literal["second_person", "named_actor"] = "second_person"

    @model_validator(mode="after")
    def validate_public_scope(self) -> OpeningNarrationContext:
        actor_ids = [participant.actor_id for participant in self.participants]
        if len(actor_ids) != len(set(actor_ids)):
            raise ValueError("OpeningNarrationContext participant actor_id 必须唯一")
        if len(self.participants) > 1 and self.solo_background_summary:
            raise ValueError("多人公共开场不得包含单人背景摘要")
        return self
