"""Compatibility adapter for an existing one-shot IntentModelPort."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator

from collaboration_framework.host.ports import IntentModelPort
from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentEvent,
    HostAgentFailed,
    HostAgentUsage,
    IntentContext,
)


class OneShotHostAgentAdapter:
    """Expose a model without tools through the single HostAgentPort contract."""

    def __init__(self, model: IntentModelPort) -> None:
        self._model = model

    async def astream(
        self,
        context: HostAgentContext,
    ) -> AsyncIterator[HostAgentEvent]:
        started_at = time.monotonic()
        try:
            raw = await self._model.generate(
                IntentContext(
                    player_input=context.player_input,
                    player_view=context.player_view,
                    recent_history=context.recent_history,
                )
            )
            yield HostAgentCompleted(
                type="agent.completed",
                raw_output=raw,
                usage=HostAgentUsage(
                    model_rounds=1,
                    tool_calls=0,
                    duration_ms=max(
                        0,
                        int((time.monotonic() - started_at) * 1000),
                    ),
                    termination_reason="completed",
                ),
            )
        except Exception:  # noqa: BLE001 - normalize arbitrary provider failures
            yield HostAgentFailed(
                type="agent.failed",
                code="HOST_AGENT_INTERNAL_ERROR",
                retryable=True,
                usage=HostAgentUsage(
                    model_rounds=1,
                    tool_calls=0,
                    duration_ms=max(
                        0,
                        int((time.monotonic() - started_at) * 1000),
                    ),
                    termination_reason="internal_error",
                ),
            )
