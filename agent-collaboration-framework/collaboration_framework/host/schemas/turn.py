"""Ephemeral member-A workflow state. This is not a shared contract."""

from typing import Literal

from collaboration_framework.contracts import (
    ActionResult,
    ContractModel,
    Intent,
    PlayerInput,
    PlayerView,
)

from .output import NarrationOutput


class TurnState(ContractModel):
    player_input: PlayerInput
    view_before: PlayerView | None = None
    intent: Intent | None = None
    action_result: ActionResult | None = None
    view_after: PlayerView | None = None
    narration: NarrationOutput | None = None
    status: Literal["running", "completed", "clarification"] = "running"
