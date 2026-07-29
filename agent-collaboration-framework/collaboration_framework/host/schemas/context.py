"""Host-only model contexts; never imported by the engine or module parser."""

from __future__ import annotations

from pydantic import Field, model_validator

from collaboration_framework.contracts import (
    ActionResult,
    ContractModel,
    Intent,
    PlayerInput,
    PlayerView,
)
from collaboration_framework.host.schemas.history import RecentTurnContext


class IntentContext(ContractModel):
    player_input: PlayerInput
    player_view: PlayerView
    recent_history: RecentTurnContext

    @model_validator(mode="after")
    def validate_scope(self) -> IntentContext:
        self.recent_history.validate_for(
            player_input=self.player_input,
            player_view=self.player_view,
        )
        return self


class NarrationContext(ContractModel):
    background: str = Field(
        min_length=1,
        description="本次叙述必须遵循的模组时代、故事前提与叙事基调。",
    )
    player_input: PlayerInput
    intent: Intent
    action_result: ActionResult
    player_view: PlayerView
    recent_history: RecentTurnContext

    @model_validator(mode="after")
    def validate_scope(self) -> NarrationContext:
        self.recent_history.validate_for(
            player_input=self.player_input,
            player_view=self.player_view,
        )
        return self
