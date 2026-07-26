"""Deterministic no-network Host Agent contract fixture."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentEvent,
    HostAgentFailed,
    HostAgentTerminalEvent,
    HostAgentToolCompleted,
    HostAgentToolStarted,
    HostAgentUsage,
    IntentContext,
)

from .intent_model import FakeIntentModel


class FakeHostAgent:
    """Deterministic offline HostAgentPort and configurable contract fixture."""

    def __init__(
        self,
        terminal_event: HostAgentTerminalEvent | None = None,
        *,
        tool_name: str | None = "search_visible_entities",
        call_id: str = "fake_tool_call_001",
        tool_status: Literal["success", "error"] = "success",
    ) -> None:
        if terminal_event is not None and not isinstance(
            terminal_event,
            (HostAgentCompleted, HostAgentFailed),
        ):
            raise TypeError(
                "FakeHostAgent terminal_event 必须为 agent.completed 或 agent.failed"
            )
        self._terminal_event = terminal_event
        self._tool_name = tool_name
        self._call_id = call_id
        self._tool_status = tool_status

    async def astream(
        self,
        context: HostAgentContext,
    ) -> AsyncIterator[HostAgentEvent]:
        # The fake has no authority-bearing dependency and consumes only the
        # already validated player-safe context required by HostAgentPort.
        if self._tool_name is not None:
            yield HostAgentToolStarted(
                type="tool.started",
                call_id=self._call_id,
                tool_name=self._tool_name,
            )
            yield HostAgentToolCompleted(
                type="tool.completed",
                call_id=self._call_id,
                tool_name=self._tool_name,
                status=self._tool_status,
            )
        if self._terminal_event is not None:
            yield self._terminal_event
            return
        raw = await FakeIntentModel().generate(
            IntentContext(
                player_input=context.player_input,
                player_view=context.player_view,
            )
        )
        yield HostAgentCompleted(
            type="agent.completed",
            raw_output=raw,
            usage=HostAgentUsage(
                model_rounds=1,
                tool_calls=0,
                duration_ms=0,
                termination_reason="completed",
            ),
        )
