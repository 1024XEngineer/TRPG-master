"""Host-only model contexts; never imported by the engine or module parser."""

from pydantic import Field

from collaboration_framework.contracts import (
    ActionResult,
    ContractModel,
    Intent,
    PlayerInput,
    PlayerView,
)


class IntentContext(ContractModel):
    player_input: PlayerInput
    player_view: PlayerView


class NarrationContext(ContractModel):
    background: str = Field(
        min_length=1,
        description="本次叙述必须遵循的模组时代、故事前提与叙事基调。",
    )
    player_input: PlayerInput
    intent: Intent
    action_result: ActionResult
    player_view: PlayerView
