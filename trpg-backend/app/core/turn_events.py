"""Player-safe internal progress events for one turn orchestration run."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Literal

from pydantic import BaseModel, ConfigDict

TurnPhase = Literal[
    "reading_player_view",
    "understanding_action",
    "waiting_for_check",
    "executing_action",
    "refreshing_player_view",
    "generating_narration",
]


class _TurnEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    correlation_id: str


class TurnStarted(_TurnEvent):
    type: Literal["turn.started"] = "turn.started"


class TurnPhaseChanged(_TurnEvent):
    type: Literal["turn.phase_changed"] = "turn.phase_changed"
    phase: TurnPhase


class TurnToolStarted(_TurnEvent):
    type: Literal["tool.started"] = "tool.started"
    tool_name: str
    public_progress_label: str


class TurnToolCompleted(_TurnEvent):
    type: Literal["tool.completed"] = "tool.completed"
    tool_name: str
    status: Literal["success", "error"]


class TurnFailed(_TurnEvent):
    type: Literal["turn.failed"] = "turn.failed"
    code: str
    public_message: str
    retryable: bool


TurnEvent = TurnStarted | TurnPhaseChanged | TurnToolStarted | TurnToolCompleted | TurnFailed
TurnEventSink = Callable[[TurnEvent], Awaitable[None]]


async def emit_turn_event(
    sink: TurnEventSink | None,
    event: TurnEvent,
) -> None:
    if sink is not None:
        await sink(event)


__all__ = [
    "TurnEvent",
    "TurnEventSink",
    "TurnFailed",
    "TurnPhase",
    "TurnPhaseChanged",
    "TurnStarted",
    "TurnToolCompleted",
    "TurnToolStarted",
    "emit_turn_event",
]
