"""Single application boundary between a Host Agent stream and trusted Intent."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from pydantic import ValidationError

from collaboration_framework.contracts import ContractError, Intent
from collaboration_framework.host.ports import HostAgentPort
from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentEvent,
    HostAgentFailed,
    HostAgentTerminalEvent,
    IntentContext,
)

from .intent_parser import IntentParser

HostAgentEventObserver = Callable[[HostAgentEvent], Awaitable[None]]


class TurnExecutionError(RuntimeError):
    """Stable, player-safe failure raised before the authoritative engine boundary."""

    def __init__(
        self,
        code: str,
        public_message: str,
        *,
        retryable: bool,
    ) -> None:
        super().__init__(public_message)
        self.code = code
        self.public_message = public_message
        self.retryable = retryable


class HostAgentIntentResolver:
    """Consume exactly one HostAgentPort run and validate its final raw JSON."""

    def __init__(self, host_agent: HostAgentPort) -> None:
        self._host_agent = host_agent

    async def resolve(
        self,
        context: HostAgentContext,
        *,
        on_event: HostAgentEventObserver | None = None,
    ) -> Intent:
        terminal: HostAgentTerminalEvent | None = None
        try:
            async for event in self._host_agent.astream(context):
                if terminal is not None:
                    raise TurnExecutionError(
                        "HOST_AGENT_STREAM_INVALID",
                        "主持 Agent 返回了非法事件序列，请重试",
                        retryable=True,
                    )
                if on_event is not None:
                    await on_event(event)
                if isinstance(event, (HostAgentCompleted, HostAgentFailed)):
                    terminal = event
        except TurnExecutionError:
            raise
        except Exception as exc:
            raise TurnExecutionError(
                "HOST_AGENT_INTERNAL_ERROR",
                "主持 Agent 运行失败，请重试",
                retryable=True,
            ) from exc

        if terminal is None:
            raise TurnExecutionError(
                "HOST_AGENT_STREAM_INVALID",
                "主持 Agent 未返回完成结果，请重试",
                retryable=True,
            )
        if isinstance(terminal, HostAgentFailed):
            raise TurnExecutionError(
                terminal.code,
                _public_failure_message(terminal.code),
                retryable=terminal.retryable,
            )

        intent_context = IntentContext(
            player_input=context.player_input,
            player_view=context.player_view,
        )
        try:
            return IntentParser.parse(terminal.raw_output, intent_context)
        except (ContractError, ValidationError, TypeError, ValueError) as exc:
            raise TurnExecutionError(
                "HOST_AGENT_INVALID_OUTPUT",
                "主持 Agent 返回的行动意图未通过安全校验，请重试",
                retryable=True,
            ) from exc


def _public_failure_message(code: str) -> str:
    if code == "HOST_AGENT_TIMEOUT":
        return "主持 Agent 响应超时，请重试"
    if code == "HOST_AGENT_MAX_TURNS":
        return "主持 Agent 未能在限定轮次内理解行动，请换一种说法后重试"
    if code == "HOST_AGENT_TOOL_BUDGET_EXCEEDED":
        return "主持 Agent 查询次数超出限制，请缩小行动范围后重试"
    if code == "HOST_AGENT_INVALID_OUTPUT":
        return "主持 Agent 返回的行动意图无效，请重试"
    return "主持 Agent 运行失败，请重试"
