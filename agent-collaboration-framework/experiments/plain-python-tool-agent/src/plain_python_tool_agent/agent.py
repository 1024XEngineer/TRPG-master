"""A streaming model -> tool -> model loop written without an agent framework."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, AsyncIterator

from openai import AsyncOpenAI

from .config import Settings
from .tools import OPENAI_TOOLS, TOOL_REGISTRY


SYSTEM_PROMPT = """You are a concise educational assistant in a generic agent example.
Use the provided tools whenever arithmetic or current-time information is requested.
Never invent a tool result. After a tool returns, answer the user in one short sentence."""


@dataclass(frozen=True, slots=True)
class TextDelta:
    text: str


@dataclass(frozen=True, slots=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    name: str
    output: dict[str, Any]
    is_error: bool


@dataclass(frozen=True, slots=True)
class Completed:
    model_rounds: int
    prompt_tokens: int
    completion_tokens: int


AgentEvent = TextDelta | ToolCall | ToolResult | Completed


@dataclass(slots=True)
class _PendingToolCall:
    call_id: str = ""
    name: str = ""
    arguments_json: str = ""


class PlainPythonAgent:
    """Explicitly manages messages, streamed tool calls, execution, and loop limits."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: Any | None = None,
        max_model_rounds: int = 6,
    ) -> None:
        self.settings = settings or Settings.from_env()
        self.client = client or AsyncOpenAI(
            api_key=self.settings.api_key,
            base_url=self.settings.base_url,
        )
        self.max_model_rounds = max_model_rounds

    async def astream(self, user_message: str) -> AsyncIterator[AgentEvent]:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ]
        prompt_tokens = 0
        completion_tokens = 0

        for model_round in range(1, self.max_model_rounds + 1):
            stream = await self.client.chat.completions.create(
                model=self.settings.model,
                messages=messages,
                tools=OPENAI_TOOLS,
                stream=True,
                stream_options={"include_usage": True},
                temperature=0,
                extra_body={"enable_thinking": False},
            )
            text_parts: list[str] = []
            pending_calls: dict[int, _PendingToolCall] = {}

            async for chunk in stream:
                if chunk.usage:
                    prompt_tokens += chunk.usage.prompt_tokens or 0
                    completion_tokens += chunk.usage.completion_tokens or 0
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                if delta.content:
                    text_parts.append(delta.content)
                    yield TextDelta(delta.content)
                for fragment in delta.tool_calls or []:
                    pending = pending_calls.setdefault(
                        fragment.index, _PendingToolCall()
                    )
                    if fragment.id:
                        pending.call_id += fragment.id
                    if fragment.function:
                        pending.name += fragment.function.name or ""
                        pending.arguments_json += fragment.function.arguments or ""

            if not pending_calls:
                yield Completed(model_round, prompt_tokens, completion_tokens)
                return

            assistant_tool_calls: list[dict[str, Any]] = []
            parsed_calls: list[ToolCall] = []
            for index in sorted(pending_calls):
                pending = pending_calls[index]
                call_id = pending.call_id or f"tool_call_{model_round}_{index}"
                try:
                    arguments = json.loads(pending.arguments_json or "{}")
                    if not isinstance(arguments, dict):
                        raise ValueError("tool arguments must be a JSON object")
                except (json.JSONDecodeError, ValueError) as exc:
                    arguments = {
                        "_invalid_json": pending.arguments_json,
                        "_error": str(exc),
                    }
                parsed_call = ToolCall(call_id, pending.name, arguments)
                parsed_calls.append(parsed_call)
                assistant_tool_calls.append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": pending.name,
                            "arguments": pending.arguments_json or "{}",
                        },
                    }
                )

            messages.append(
                {
                    "role": "assistant",
                    "content": "".join(text_parts) or None,
                    "tool_calls": assistant_tool_calls,
                }
            )
            for tool_call in parsed_calls:
                yield tool_call
                result = self._execute_tool(tool_call)
                yield result
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.call_id,
                        "content": json.dumps(result.output, ensure_ascii=False),
                    }
                )

        raise RuntimeError(
            f"Agent exceeded max_model_rounds={self.max_model_rounds} without a final answer"
        )

    @staticmethod
    def _execute_tool(tool_call: ToolCall) -> ToolResult:
        tool = TOOL_REGISTRY.get(tool_call.name)
        if tool is None:
            return ToolResult(
                tool_call.call_id,
                tool_call.name,
                {"error": f"Unknown tool: {tool_call.name}"},
                True,
            )
        if "_invalid_json" in tool_call.arguments:
            return ToolResult(
                tool_call.call_id,
                tool_call.name,
                {"error": tool_call.arguments["_error"]},
                True,
            )
        try:
            output = tool.handler(**tool_call.arguments)
        except (TypeError, ValueError) as exc:
            return ToolResult(
                tool_call.call_id, tool_call.name, {"error": str(exc)}, True
            )
        return ToolResult(tool_call.call_id, tool_call.name, output, False)
