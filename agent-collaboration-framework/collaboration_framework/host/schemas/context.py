"""Host-only model contexts; never imported by the engine or module parser."""

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
    player_input: PlayerInput
    intent: Intent
    action_result: ActionResult
    player_view: PlayerView
