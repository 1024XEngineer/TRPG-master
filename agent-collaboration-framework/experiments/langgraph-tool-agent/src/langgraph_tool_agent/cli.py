"""Command-line entry point for the LangGraph ecosystem example."""

from __future__ import annotations

import argparse
import asyncio
import json

from .agent import Completed, LangGraphAgent, TextDelta, ToolCall, ToolResult


DEFAULT_QUESTION = "Use a tool to calculate 23.5 + 18.25, then answer in one sentence."


async def _run(question: str) -> None:
    agent = LangGraphAgent()
    text_started = False
    async for event in agent.astream(question):
        if isinstance(event, TextDelta):
            print(event.text, end="", flush=True)
            text_started = True
        elif isinstance(event, ToolCall):
            if text_started:
                print()
                text_started = False
            arguments = json.dumps(event.arguments, ensure_ascii=False)
            print(f"[tool call] {event.name}({arguments})")
        elif isinstance(event, ToolResult):
            print(f"[tool result] {event.output}")
        elif isinstance(event, Completed):
            if text_started:
                print()
            print(f"[done] rounds={event.model_rounds}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the LangGraph ecosystem tool agent."
    )
    parser.add_argument("question", nargs="?", default=DEFAULT_QUESTION)
    args = parser.parse_args()
    asyncio.run(_run(args.question))


if __name__ == "__main__":
    main()
