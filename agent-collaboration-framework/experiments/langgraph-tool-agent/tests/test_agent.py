from __future__ import annotations

import unittest
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from langgraph_tool_agent.agent import (
    Completed,
    LangGraphAgent,
    TextDelta,
    ToolCall,
    ToolResult,
)


class FakeToolCallingModel(BaseChatModel):
    model_calls: int = 0
    bound_tool_names: tuple[str, ...] = ()

    @property
    def _llm_type(self) -> str:
        return "fake-tool-calling-model"

    def bind_tools(self, tools, *, tool_choice=None, **kwargs):
        self.bound_tool_names = tuple(tool.name for tool in tools)
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: Any = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.model_calls += 1
        if not any(isinstance(message, ToolMessage) for message in messages):
            response = AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "add_numbers",
                        "args": {"a": 23.5, "b": 18.25},
                        "id": "call_1",
                        "type": "tool_call",
                    }
                ],
            )
        else:
            response = AIMessage(content="The sum is 41.75.")
        return ChatResult(generations=[ChatGeneration(message=response)])


class LangGraphAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_agent_binds_tools_executes_and_streams(self):
        model = FakeToolCallingModel()
        agent = LangGraphAgent(model=model)

        events = [event async for event in agent.astream("Please add two numbers")]

        call = next(event for event in events if isinstance(event, ToolCall))
        result = next(event for event in events if isinstance(event, ToolResult))
        done = next(event for event in events if isinstance(event, Completed))
        self.assertEqual(
            set(model.bound_tool_names), {"add_numbers", "get_current_time"}
        )
        self.assertEqual(call.arguments, {"a": 23.5, "b": 18.25})
        self.assertIn("41.75", str(result.output))
        self.assertFalse(result.is_error)
        self.assertEqual(
            "".join(e.text for e in events if isinstance(e, TextDelta)),
            "The sum is 41.75.",
        )
        self.assertEqual(done.model_rounds, 2)
        self.assertEqual(model.model_calls, 2)


if __name__ == "__main__":
    unittest.main()
