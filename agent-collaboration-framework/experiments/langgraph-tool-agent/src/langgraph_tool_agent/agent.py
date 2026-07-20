"""A compact create_agent wrapper with observable streaming events."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, AsyncIterator

from langchain.agents import create_agent
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, ToolMessage
from langchain_openai import ChatOpenAI

from .config import Settings
from .tools import TOOLS


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
    output: Any
    is_error: bool


@dataclass(frozen=True, slots=True)
class Completed:
    model_rounds: int


AgentEvent = TextDelta | ToolCall | ToolResult | Completed


def build_agent(model: BaseChatModel):
    """The complete agent orchestration: one model, two tools, one system prompt."""
    return create_agent(model=model, tools=TOOLS, system_prompt=SYSTEM_PROMPT)


class LangGraphAgent:
    """Expose LangGraph's message/update streams as small teaching events."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        model: BaseChatModel | None = None,
    ) -> None:
        if model is None:
            resolved = settings or Settings.from_env()
            model = ChatOpenAI(
                model=resolved.model,
                api_key=resolved.api_key,
                base_url=resolved.base_url,
                temperature=0,
                stream_usage=True,
                extra_body={"enable_thinking": False},
            )
        self.graph = build_agent(model)

    async def astream(self, user_message: str) -> AsyncIterator[AgentEvent]:
        model_rounds = 0
        stream = self.graph.astream(
            {"messages": [{"role": "user", "content": user_message}]},
            stream_mode=["messages", "updates"],
        )
        async for mode, payload in stream:
            if mode == "messages":
                message, _metadata = payload
                # Streaming models yield AIMessageChunk; non-streaming/fake models
                # can fall back to a complete AIMessage in the same stream mode.
                if isinstance(message, (AIMessageChunk, AIMessage)):
                    text = _text_content(message.content)
                    if text:
                        yield TextDelta(text)
                continue

            for node_name, update in payload.items():
                if node_name == "model":
                    model_rounds += 1
                for message in update.get("messages", []):
                    if isinstance(message, AIMessage):
                        for call in message.tool_calls:
                            yield ToolCall(call["id"], call["name"], call["args"])
                    elif isinstance(message, ToolMessage):
                        yield ToolResult(
                            call_id=message.tool_call_id,
                            name=message.name or "",
                            output=message.content,
                            is_error=message.status == "error",
                        )
        yield Completed(model_rounds)


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""
