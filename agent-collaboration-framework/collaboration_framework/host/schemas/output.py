"""Host-internal turn result and player-safe WebSocket envelope."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from collaboration_framework.contracts import (
    ActionResult,
    ContractError,
    ContractModel,
    Intent,
    PlayerInput,
    PlayerView,
)


class NarrationOutput(ContractModel):
    kind: Literal["narration", "clarification"] = "narration"
    text: str = Field(min_length=1)
    claimed_fact_ids: tuple[str, ...] = ()
    suggested_actions: tuple[str, ...] = ()


class PlayerTurnPayload(ContractModel):
    room_id: str
    player_id: str
    actor_id: str
    narration: NarrationOutput
    player_view: PlayerView


class WebSocketOutput(ContractModel):
    protocol_version: Literal["1"] = "1"
    message_type: Literal["turn.completed"] = "turn.completed"
    correlation_id: str = Field(min_length=1)
    payload: PlayerTurnPayload


class TurnOutput(ContractModel):
    """Host-internal result; convert before sending to a player."""

    status: Literal["completed", "clarification"]
    player_input: PlayerInput
    intent: Intent
    action_result: ActionResult
    narration: NarrationOutput
    player_view: PlayerView

    @model_validator(mode="after")
    def validate_status(self) -> TurnOutput:
        expected = "clarification" if self.narration.kind == "clarification" else "completed"
        if self.status != expected:
            raise ValueError("TurnOutput.status 必须与 NarrationOutput.kind 一致")
        return self

    def to_websocket_output(self) -> WebSocketOutput:
        if self.player_input.room_id != self.player_view.room_id:
            raise ContractError("输出 PlayerView 与 PlayerInput 房间不一致")
        return WebSocketOutput(
            correlation_id=self.player_input.client_action_id,
            payload=PlayerTurnPayload(
                room_id=self.player_input.room_id,
                player_id=self.player_input.player_id,
                actor_id=self.player_input.actor_id,
                narration=self.narration,
                player_view=self.player_view,
            ),
        )
