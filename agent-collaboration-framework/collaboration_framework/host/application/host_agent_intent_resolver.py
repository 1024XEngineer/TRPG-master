"""Single application boundary between a Host Agent stream and trusted Intent."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from pydantic import ValidationError

from collaboration_framework.contracts import (
    ContractError,
    Intent,
    NoCheck,
    UnmatchedTarget,
)
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
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntentResolution:
    intent: Intent
    recovered: bool = False


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
        return (await self.resolve_with_metadata(context, on_event=on_event)).intent

    async def resolve_with_metadata(
        self,
        context: HostAgentContext,
        *,
        on_event: HostAgentEventObserver | None = None,
    ) -> IntentResolution:
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
            if terminal.code == "HOST_AGENT_INVALID_OUTPUT":
                logger.warning(
                    "host_agent_intent_recovered",
                    extra={
                        "room_id": context.player_input.room_id,
                        "player_id": context.player_input.player_id,
                        "view_revision": context.player_view.revision,
                        "failure_reason": "adapter_invalid_output",
                        "recovery_path": "unknown_intent_clarification",
                    },
                )
                return IntentResolution(_clarification_intent(context), recovered=True)
            raise TurnExecutionError(
                terminal.code,
                _public_failure_message(terminal.code),
                retryable=terminal.retryable,
            )

        intent_context = IntentContext(
            player_input=context.player_input,
            player_view=context.player_view,
            recent_history=context.recent_history,
        )
        try:
            return IntentResolution(
                IntentParser.parse(terminal.raw_output, intent_context)
            )
        except (ContractError, ValidationError, TypeError, ValueError) as exc:
            logger.warning(
                "host_agent_intent_recovered",
                extra={
                    "room_id": context.player_input.room_id,
                    "player_id": context.player_input.player_id,
                    "view_revision": context.player_view.revision,
                    "failure_reason": _recovery_reason(exc),
                    "recovery_path": "unknown_intent_clarification",
                },
            )
            return IntentResolution(_clarification_intent(context), recovered=True)


def _clarification_intent(context: HostAgentContext) -> Intent:
    """Return a state-free Intent so one bad model response cannot stop a turn."""

    utterance = context.player_input.utterance.strip() or "这次行动"
    return Intent(
        kind="unknown",
        verb="unknown",
        target=UnmatchedTarget(raw=utterance),
        check=NoCheck(),
        summary=utterance,
        clarification_question="你想对当前场景中的哪个人物、物品或地点做什么？",
    )


def _recovery_reason(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "intent_schema_invalid"
    if isinstance(exc, ContractError):
        message = str(exc)
        if "target" in message:
            return "target_not_visible_or_ambiguous"
        if "checkpoint" in message:
            return "checkpoint_not_available_or_mismatched"
        if "skill" in message or "技能" in message:
            return "skill_not_allowed"
        return "intent_contract_invalid"
    return "intent_validation_failed"


def _public_failure_message(code: str) -> str:
    if code == "HOST_AGENT_TIMEOUT":
        return "主持 Agent 响应超时，请重试"
    if code == "HOST_AGENT_MAX_TURNS":
        return "主持 Agent 未能在限定轮次内理解行动，请换一种说法后重试"
    if code == "HOST_AGENT_TOOL_BUDGET_EXCEEDED":
        return "主持 Agent 查询次数超出限制，请缩小行动范围后重试"
    if code == "HOST_AGENT_INVALID_OUTPUT":
        return "守秘人一时没能准确理解这次行动。请结合眼前的人物或物品，换一种说法。"
    return "主持 Agent 运行失败，请重试"
