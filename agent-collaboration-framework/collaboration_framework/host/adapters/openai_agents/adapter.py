"""OpenAI Agents SDK HostAgentPort implementation backed by Qwen."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
import json
import time
from typing import Any, cast

from agents import Agent, ModelSettings, RunConfig, Runner
from agents.exceptions import MaxTurnsExceeded
from agents.models.interface import Model
from pydantic import JsonValue

from collaboration_framework.host.application.tool_registry import ToolRegistry
from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentEvent,
    HostAgentFailed,
    HostAgentFailureCode,
    HostAgentTerminationReason,
    HostAgentUsage,
)

from .config import QwenHostAgentConfig
from .event_mapper import EventObservation, SDKEventMappingError
from .prompt import SYSTEM_PROMPT, build_agent_input
from .tool_adapter import (
    ToolBudgetExceeded,
    ToolRunState,
    build_sdk_tools,
)


_FAILURE_REASON_BY_CODE: dict[
    HostAgentFailureCode,
    HostAgentTerminationReason,
] = {
    "HOST_AGENT_MAX_TURNS": "max_turns",
    "HOST_AGENT_TIMEOUT": "timeout",
    "HOST_AGENT_INVALID_OUTPUT": "invalid_output",
    "HOST_AGENT_TOOL_BUDGET_EXCEEDED": "tool_budget_exceeded",
    "HOST_AGENT_INTERNAL_ERROR": "internal_error",
}


class InvalidHostAgentOutput(ValueError):
    """The model's final output was not one finite JSON object."""


class QwenHostAgentAdapter:
    """Run Qwen through the SDK while exposing only project-owned events."""

    def __init__(
        self,
        *,
        model: Model,
        tool_registry: ToolRegistry,
        config: QwenHostAgentConfig,
        runner: Any = Runner,
    ) -> None:
        self._model = model
        self._tool_registry = tool_registry
        self._config = config
        self._runner = runner

    async def astream(
        self,
        context: HostAgentContext,
    ) -> AsyncIterator[HostAgentEvent]:
        started_at = time.monotonic()
        observation = EventObservation()
        tool_state = ToolRunState(
            bound_registry=self._tool_registry.bind(context),
            max_tool_calls=self._config.max_tool_calls,
            tool_timeout_seconds=self._config.tool_timeout_seconds,
        )
        result: Any | None = None

        try:
            agent = Agent(
                name="TRPG Host Agent",
                instructions=SYSTEM_PROMPT,
                model=self._model,
                tools=build_sdk_tools(tool_state),
                model_settings=ModelSettings(
                    temperature=0,
                    parallel_tool_calls=False,
                    include_usage=True,
                    extra_body={"enable_thinking": False},
                    tool_choice="auto",
                ),
            )
            result = self._runner.run_streamed(
                agent,
                build_agent_input(context),
                max_turns=self._config.max_turns,
                run_config=RunConfig(
                    tracing_disabled=True,
                    trace_include_sensitive_data=False,
                    workflow_name="TRPG Host Agent",
                ),
            )

            async with asyncio.timeout(self._config.timeout_seconds):
                async for sdk_event in result.stream_events():
                    mapped = observation.map_event(sdk_event)
                    if mapped is not None:
                        yield mapped

            if observation.pending_tools:
                raise SDKEventMappingError(
                    "SDK run completed with unfinished tool calls"
                )

            raw_output = parse_raw_output(result.final_output)
            yield HostAgentCompleted(
                type="agent.completed",
                raw_output=raw_output,
                usage=_build_usage(
                    observation=observation,
                    tool_state=tool_state,
                    started_at=started_at,
                    reason="completed",
                ),
            )
        except MaxTurnsExceeded:
            async for event in _failure_events(
                observation=observation,
                tool_state=tool_state,
                started_at=started_at,
                code="HOST_AGENT_MAX_TURNS",
                retryable=False,
            ):
                yield event
        except ToolBudgetExceeded:
            async for event in _failure_events(
                observation=observation,
                tool_state=tool_state,
                started_at=started_at,
                code="HOST_AGENT_TOOL_BUDGET_EXCEEDED",
                retryable=False,
            ):
                yield event
        except TimeoutError:
            _cancel_result(result)
            async for event in _failure_events(
                observation=observation,
                tool_state=tool_state,
                started_at=started_at,
                code="HOST_AGENT_TIMEOUT",
                retryable=True,
            ):
                yield event
        except InvalidHostAgentOutput:
            async for event in _failure_events(
                observation=observation,
                tool_state=tool_state,
                started_at=started_at,
                code="HOST_AGENT_INVALID_OUTPUT",
                retryable=False,
            ):
                yield event
        except Exception:
            _cancel_result(result)
            async for event in _failure_events(
                observation=observation,
                tool_state=tool_state,
                started_at=started_at,
                code="HOST_AGENT_INTERNAL_ERROR",
                retryable=False,
            ):
                yield event


def parse_raw_output(value: object) -> dict[str, JsonValue]:
    """Accept one plain, finite JSON object and reject provider-native values."""

    try:
        if isinstance(value, str):
            decoded = json.loads(
                value,
                parse_constant=_reject_json_constant,
            )
        elif isinstance(value, dict):
            rendered = json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
            )
            decoded = json.loads(rendered)
        else:
            raise InvalidHostAgentOutput("final output must be a JSON object")
    except (
        json.JSONDecodeError,
        TypeError,
        ValueError,
        OverflowError,
    ) as exc:
        if isinstance(exc, InvalidHostAgentOutput):
            raise
        raise InvalidHostAgentOutput("final output is not finite JSON") from exc

    if not isinstance(decoded, dict):
        raise InvalidHostAgentOutput("final output must be a JSON object")
    return cast(dict[str, JsonValue], decoded)


def _reject_json_constant(value: str) -> None:
    raise InvalidHostAgentOutput(f"invalid JSON constant: {value}")


async def _failure_events(
    *,
    observation: EventObservation,
    tool_state: ToolRunState,
    started_at: float,
    code: HostAgentFailureCode,
    retryable: bool,
) -> AsyncIterator[HostAgentEvent]:
    for event in observation.close_pending_tools():
        yield event
    yield HostAgentFailed(
        type="agent.failed",
        code=code,
        retryable=retryable,
        usage=_build_usage(
            observation=observation,
            tool_state=tool_state,
            started_at=started_at,
            reason=_FAILURE_REASON_BY_CODE[code],
        ),
    )


def _build_usage(
    *,
    observation: EventObservation,
    tool_state: ToolRunState,
    started_at: float,
    reason: HostAgentTerminationReason,
) -> HostAgentUsage:
    return HostAgentUsage(
        model_rounds=observation.usage.model_rounds,
        tool_calls=max(observation.tool_calls, tool_state.tool_calls),
        input_tokens=observation.usage.input_tokens,
        output_tokens=observation.usage.output_tokens,
        duration_ms=max(0, int((time.monotonic() - started_at) * 1000)),
        termination_reason=reason,
    )


def _cancel_result(result: object | None) -> None:
    cancel = getattr(result, "cancel", None)
    if callable(cancel):
        cancel()
