"""Single streaming boundary for the Host Agent intent stage."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Protocol, runtime_checkable

from collaboration_framework.host.schemas import HostAgentContext, HostAgentEvent


@runtime_checkable
class HostAgentPort(Protocol):
    """Run the intent-understanding stage through one contract event stream.

    An invocation may emit zero or more tool progress events and must then emit
    exactly one ``agent.completed`` or ``agent.failed`` event. The terminal event
    is last. Completed raw output remains untrusted JSON for ``IntentParser``;
    implementations must not execute actions or otherwise mutate game state.
    """

    def astream(
        self,
        context: HostAgentContext,
    ) -> AsyncIterator[HostAgentEvent]: ...
