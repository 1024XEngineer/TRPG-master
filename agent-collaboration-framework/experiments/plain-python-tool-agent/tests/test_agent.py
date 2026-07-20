from __future__ import annotations

import unittest
from types import SimpleNamespace

from plain_python_tool_agent.agent import (
    Completed,
    PlainPythonAgent,
    TextDelta,
    ToolCall,
    ToolResult,
)
from plain_python_tool_agent.config import Settings


def chunk(*, content=None, tool_calls=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choices = [] if usage else [SimpleNamespace(delta=delta)]
    return SimpleNamespace(choices=choices, usage=usage)


def tool_fragment(index, *, call_id=None, name=None, arguments=None):
    function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=call_id, function=function)


class FakeStream:
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for item in self.chunks:
            yield item


class FakeCompletions:
    def __init__(self, rounds):
        self.rounds = list(rounds)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return FakeStream(self.rounds.pop(0))


class FakeClient:
    def __init__(self, rounds):
        self.chat = SimpleNamespace(completions=FakeCompletions(rounds))


class PlainPythonAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_streams_fragmented_tool_call_executes_it_and_finishes(self):
        usage = SimpleNamespace(prompt_tokens=20, completion_tokens=4)
        client = FakeClient(
            [
                [
                    chunk(
                        tool_calls=[
                            tool_fragment(
                                0, call_id="call_1", name="add_", arguments='{"a":23.5,'
                            )
                        ]
                    ),
                    chunk(
                        tool_calls=[
                            tool_fragment(0, name="numbers", arguments='"b":18.25}')
                        ]
                    ),
                ],
                [
                    chunk(content="The sum is "),
                    chunk(content="41.75."),
                    chunk(usage=usage),
                ],
            ]
        )
        agent = PlainPythonAgent(Settings("test-key"), client=client)

        events = [event async for event in agent.astream("Please add two numbers")]

        call = next(event for event in events if isinstance(event, ToolCall))
        result = next(event for event in events if isinstance(event, ToolResult))
        done = next(event for event in events if isinstance(event, Completed))
        self.assertEqual(call.name, "add_numbers")
        self.assertEqual(call.arguments, {"a": 23.5, "b": 18.25})
        self.assertEqual(result.output, {"sum": 41.75})
        self.assertFalse(result.is_error)
        self.assertEqual(
            "".join(e.text for e in events if isinstance(e, TextDelta)),
            "The sum is 41.75.",
        )
        self.assertEqual(done.model_rounds, 2)
        self.assertEqual((done.prompt_tokens, done.completion_tokens), (20, 4))
        second_round_messages = client.chat.completions.calls[1]["messages"]
        self.assertEqual(second_round_messages[-1]["role"], "tool")

    async def test_unknown_tool_becomes_observable_error_result(self):
        client = FakeClient(
            [
                [
                    chunk(
                        tool_calls=[
                            tool_fragment(
                                0, call_id="x", name="missing", arguments="{}"
                            )
                        ]
                    )
                ],
                [chunk(content="I could not use that tool.")],
            ]
        )
        events = [
            event
            async for event in PlainPythonAgent(
                Settings("test-key"), client=client
            ).astream("test")
        ]
        result = next(event for event in events if isinstance(event, ToolResult))
        self.assertTrue(result.is_error)
        self.assertIn("Unknown tool", result.output["error"])

    async def test_round_limit_stops_infinite_tool_loop(self):
        one_tool_round = [
            chunk(
                tool_calls=[
                    tool_fragment(
                        0, call_id="x", name="add_numbers", arguments='{"a":1,"b":2}'
                    )
                ]
            )
        ]
        agent = PlainPythonAgent(
            Settings("test-key"),
            client=FakeClient([one_tool_round]),
            max_model_rounds=1,
        )
        with self.assertRaisesRegex(RuntimeError, "max_model_rounds=1"):
            _ = [event async for event in agent.astream("loop")]


if __name__ == "__main__":
    unittest.main()
