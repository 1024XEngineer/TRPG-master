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
)


class FakeHostAgent:
    """Emit an optional fake tool pair and one caller-supplied terminal event."""

    def __init__(
        self,
        terminal_event: HostAgentTerminalEvent,
        *,
        tool_name: str | None = "search_visible_entities",
        call_id: str = "fake_tool_call_001",
        tool_status: Literal["success", "error"] = "success",
    ) -> None:
        if not isinstance(terminal_event, (HostAgentCompleted, HostAgentFailed)):
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
        # The fake deliberately has no authority-bearing dependency and only
        # accepts the already validated context required by HostAgentPort.
        del context
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
        yield self._terminal_event
