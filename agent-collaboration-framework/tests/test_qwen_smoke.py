from __future__ import annotations

from datetime import date
from importlib.metadata import version
import json
import os
import unittest

from collaboration_framework.bootstrap.host_agent import build_qwen_host_agent
from collaboration_framework.contracts import (
    CheckpointOption,
    PlayerInput,
    PlayerView,
    VisibleEntity,
)
from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentFailed,
    HostAgentToolCompleted,
    HostAgentToolStarted,
)


RUN_QWEN_SMOKE = os.getenv("RUN_QWEN_SMOKE") == "1"


def make_context(utterance: str) -> HostAgentContext:
    return HostAgentContext(
        player_input=PlayerInput(
            room_id="smoke_room",
            player_id="smoke_player",
            actor_id="smoke_actor",
            client_action_id="smoke_action",
            utterance=utterance,
        ),
        player_view=PlayerView(
            room_id="smoke_room",
            player_id="smoke_player",
            actor_id="smoke_actor",
            scene_id="smoke_library",
            phase="playing",
            revision="1",
            visible_entities=(
                VisibleEntity(
                    id="smoke_bookshelf_42",
                    kind="object",
                    name="红色书架",
                    aliases=("书架",),
                    content="一个玩家当前可见的红色木书架。",
                ),
            ),
            checkpoint_options=(
                CheckpointOption(
                    id="smoke_checkpoint_search",
                    target_id="smoke_bookshelf_42",
                    action_hint="仔细检查书架",
                    skills=("侦查",),
                ),
            ),
        ),
    )


@unittest.skipUnless(
    RUN_QWEN_SMOKE,
    "set RUN_QWEN_SMOKE=1 to run real Qwen adapter smoke tests",
)
class RealQwenAdapterSmokeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls) -> None:
        super().setUpClass()
        if not os.getenv("HOST_AGENT_API_KEY", "").strip():
            raise AssertionError(
                "RUN_QWEN_SMOKE=1 requires HOST_AGENT_API_KEY"
            )
        print(
            "Qwen smoke metadata: "
            f"date={date.today().isoformat()} "
            f"model={os.getenv('HOST_AGENT_MODEL', 'qwen-plus')} "
            f"openai-agents={version('openai-agents')} "
            f"openai={version('openai')}"
        )

    async def run_agent(
        self,
        utterance: str,
    ) -> tuple[object, ...]:
        adapter = build_qwen_host_agent()
        events = tuple(
            [event async for event in adapter.astream(make_context(utterance))]
        )
        self.assertTrue(events)
        terminals = [
            event
            for event in events
            if isinstance(event, (HostAgentCompleted, HostAgentFailed))
        ]
        self.assertEqual(len(terminals), 1)
        self.assertIsInstance(events[-1], HostAgentCompleted)

        started = {
            event.call_id: event.tool_name
            for event in events
            if isinstance(event, HostAgentToolStarted)
        }
        completed = {
            event.call_id: event.tool_name
            for event in events
            if isinstance(event, HostAgentToolCompleted)
        }
        self.assertEqual(started, completed)

        forbidden_fields = {
            "arguments",
            "raw_result",
            "prompt",
            "reasoning",
            "sdk_result",
        }
        for event in events:
            self.assertTrue(
                forbidden_fields.isdisjoint(event.model_fields)
            )

        rendered_output = json.dumps(
            events[-1].raw_output,
            ensure_ascii=False,
            allow_nan=False,
        )
        self.assertIsInstance(json.loads(rendered_output), dict)
        return events

    async def test_single_search_tool_then_final(self) -> None:
        events = await self.run_agent(
            "必须先调用 search_visible_entities 搜索“红色书架”，"
            "拿到结果后再输出我要检查它的 Intent。"
        )
        self.assertEqual(
            [
                event.tool_name
                for event in events
                if isinstance(event, HostAgentToolStarted)
            ],
            ["search_visible_entities"],
        )
        self.assertEqual(
            [event.type for event in events],
            ["tool.started", "tool.completed", "agent.completed"],
        )

    async def test_search_then_get_uses_previous_result(self) -> None:
        events = await self.run_agent(
            "必须先调用 search_visible_entities 搜索“红色书架”，"
            "再把搜索返回的实体 ID 传给 get_visible_entity，"
            "最后输出我要仔细检查书架的 Intent。"
        )
        self.assertEqual(
            [
                event.tool_name
                for event in events
                if isinstance(event, HostAgentToolStarted)
            ],
            ["search_visible_entities", "get_visible_entity"],
        )
        self.assertEqual(
            [event.type for event in events],
            [
                "tool.started",
                "tool.completed",
                "tool.started",
                "tool.completed",
                "agent.completed",
            ],
        )

    async def test_tool_error_is_returned_safely_and_agent_recovers(self) -> None:
        events = await self.run_agent(
            "先调用 get_visible_entity，entity_id 使用 missing_entity，"
            "如果工具报告不可见，不要猜测，输出合法 unknown Intent。"
        )
        completed_tools = [
            event
            for event in events
            if isinstance(event, HostAgentToolCompleted)
        ]
        self.assertTrue(completed_tools)
        self.assertEqual(completed_tools[0].status, "error")
        self.assertEqual(
            [event.type for event in events],
            ["tool.started", "tool.completed", "agent.completed"],
        )
        self.assertEqual(events[-1].raw_output["kind"], "unknown")


if __name__ == "__main__":
    unittest.main()
