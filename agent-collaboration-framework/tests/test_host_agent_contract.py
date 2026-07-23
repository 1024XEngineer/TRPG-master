from __future__ import annotations

import json
import unittest

from pydantic import TypeAdapter, ValidationError

from collaboration_framework.contracts import PlayerInput, PlayerView
from collaboration_framework.host.adapters.fakes import FakeHostAgent
from collaboration_framework.host.ports import HostAgentPort
from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentEvent,
    HostAgentFailed,
    HostAgentTerminalEvent,
    HostAgentToolCompleted,
    HostAgentToolStarted,
    HostAgentUsage,
)
from collaboration_framework.schema_export import rendered_schemas


RAW_INTENT_CANDIDATE = {
    "kind": "unknown",
    "verb": "unknown",
    "target": {"matched": False, "raw": "不清楚的行动"},
    "check": {"route": "none"},
    "summary": "不清楚的行动",
    "clarification_question": "你想做什么？",
}


def make_usage(
    termination_reason: str = "completed",
    *,
    tool_calls: int = 1,
) -> HostAgentUsage:
    return HostAgentUsage(
        model_rounds=2,
        tool_calls=tool_calls,
        input_tokens=24,
        output_tokens=12,
        duration_ms=7,
        termination_reason=termination_reason,
    )


class HostAgentPortContractMixin:
    """Reusable stream assertions for Fake and future SDK adapters."""

    async def assert_host_agent_port_contract(
        self,
        port: HostAgentPort,
        context: HostAgentContext,
    ) -> tuple[HostAgentEvent, ...]:
        events = tuple([event async for event in port.astream(context)])
        allowed_event_types = (
            HostAgentToolStarted,
            HostAgentToolCompleted,
            HostAgentCompleted,
            HostAgentFailed,
        )
        for event in events:
            self.assertIsInstance(event, allowed_event_types)
        terminals = [
            (index, event)
            for index, event in enumerate(events)
            if isinstance(event, (HostAgentCompleted, HostAgentFailed))
        ]
        self.assertEqual(len(terminals), 1)
        self.assertEqual(terminals[0][0], len(events) - 1)
        return events


class HostAgentSchemaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.player_input = PlayerInput(
            room_id="room_001",
            player_id="player_001",
            actor_id="actor_001",
            client_action_id="action_001",
            utterance="检查书架",
        )
        self.player_view = PlayerView(
            room_id="room_001",
            player_id="player_001",
            actor_id="actor_001",
            scene_id="library",
            phase="playing",
            revision="7",
        )

    def test_context_accepts_only_matching_trusted_scope(self) -> None:
        context = HostAgentContext(
            player_input=self.player_input,
            player_view=self.player_view,
        )
        self.assertEqual(
            set(HostAgentContext.model_fields),
            {"player_input", "player_view"},
        )
        self.assertEqual(
            set(context.to_json_dict()),
            {"player_input", "player_view"},
        )

        with self.assertRaises(ValidationError):
            HostAgentContext.model_validate(
                {
                    "player_input": self.player_input,
                    "player_view": self.player_view,
                    "game_state": {},
                }
            )

    def test_context_rejects_each_scope_mismatch(self) -> None:
        for field_name in ("room_id", "player_id", "actor_id"):
            mismatched_view = self.player_view.model_copy(
                update={field_name: f"other_{field_name}"}
            )
            with self.subTest(field_name=field_name):
                with self.assertRaisesRegex(ValidationError, "scope 不一致"):
                    HostAgentContext(
                        player_input=self.player_input,
                        player_view=mismatched_view,
                    )

    def test_usage_distinguishes_unreported_tokens_from_reported_zero(self) -> None:
        unreported = HostAgentUsage(
            model_rounds=1,
            tool_calls=0,
            duration_ms=3,
            termination_reason="completed",
        )
        self.assertIsNone(unreported.input_tokens)
        self.assertIsNone(unreported.output_tokens)
        self.assertIsNone(unreported.to_json_dict()["input_tokens"])
        self.assertIsNone(unreported.to_json_dict()["output_tokens"])

        reported_zero = unreported.model_copy(
            update={"input_tokens": 0, "output_tokens": 0}
        )
        self.assertEqual(reported_zero.input_tokens, 0)
        self.assertEqual(reported_zero.output_tokens, 0)

    def test_usage_rejects_negative_measurements_and_unstable_reasons(self) -> None:
        for field_name in (
            "model_rounds",
            "tool_calls",
            "input_tokens",
            "output_tokens",
            "duration_ms",
        ):
            payload = make_usage().model_dump()
            payload[field_name] = -1
            with self.subTest(field_name=field_name):
                with self.assertRaises(ValidationError):
                    HostAgentUsage.model_validate(payload)

        payload = make_usage().model_dump()
        payload["termination_reason"] = "provider_specific_finish_reason"
        with self.assertRaises(ValidationError):
            HostAgentUsage.model_validate(payload)

    def test_events_are_discriminated_and_round_trip_as_json(self) -> None:
        adapter = TypeAdapter(HostAgentEvent)
        events: tuple[HostAgentEvent, ...] = (
            HostAgentToolStarted(
                type="tool.started",
                call_id="call_001",
                tool_name="visible_lookup",
            ),
            HostAgentToolCompleted(
                type="tool.completed",
                call_id="call_001",
                tool_name="visible_lookup",
                status="success",
            ),
            HostAgentCompleted(
                type="agent.completed",
                raw_output=RAW_INTENT_CANDIDATE,
                usage=make_usage(),
            ),
            HostAgentFailed(
                type="agent.failed",
                code="HOST_AGENT_TIMEOUT",
                retryable=True,
                usage=make_usage("timeout"),
            ),
        )
        for event in events:
            with self.subTest(event=event.type):
                payload = json.loads(event.model_dump_json())
                parsed = adapter.validate_python(payload)
                self.assertEqual(parsed, event)
                self.assertEqual(parsed.type, payload["type"])

    def test_event_shapes_exclude_sensitive_and_sdk_fields(self) -> None:
        forbidden_fields = {
            "reasoning",
            "prompt",
            "api_key",
            "sdk_result",
            "arguments",
            "raw_result",
            "secret_context",
        }
        event_models = (
            HostAgentToolStarted,
            HostAgentToolCompleted,
            HostAgentCompleted,
            HostAgentFailed,
        )
        for event_model in event_models:
            with self.subTest(event_model=event_model.__name__):
                self.assertTrue(forbidden_fields.isdisjoint(event_model.model_fields))

        with self.assertRaises(ValidationError):
            HostAgentToolStarted.model_validate(
                {
                    "type": "tool.started",
                    "call_id": "call_001",
                    "tool_name": "visible_lookup",
                    "arguments": {"room_id": "other_room"},
                }
            )
        with self.assertRaises(ValidationError):
            HostAgentCompleted(
                type="agent.completed",
                raw_output={"sdk_object": object()},
                usage=make_usage(),
            )
        with self.assertRaises(ValueError):
            HostAgentCompleted(
                type="agent.completed",
                raw_output={"score": float("nan")},
                usage=make_usage(),
            )

    def test_completed_and_failed_are_mutually_exclusive(self) -> None:
        adapter = TypeAdapter(HostAgentEvent)
        completed = HostAgentCompleted(
            type="agent.completed",
            raw_output=RAW_INTENT_CANDIDATE,
            usage=make_usage(),
        ).to_json_dict()
        failed = HostAgentFailed(
            type="agent.failed",
            code="HOST_AGENT_INTERNAL_ERROR",
            retryable=False,
        ).to_json_dict()

        with self.assertRaises(ValidationError):
            adapter.validate_python(
                {**completed, "code": "HOST_AGENT_INTERNAL_ERROR"}
            )
        with self.assertRaises(ValidationError):
            adapter.validate_python(
                {**failed, "raw_output": RAW_INTENT_CANDIDATE}
            )

    def test_terminal_usage_reason_must_match_terminal_semantics(self) -> None:
        with self.assertRaisesRegex(ValidationError, "必须为 completed"):
            HostAgentCompleted(
                type="agent.completed",
                raw_output=RAW_INTENT_CANDIDATE,
                usage=make_usage("timeout"),
            )
        with self.assertRaisesRegex(ValidationError, "code 与"):
            HostAgentFailed(
                type="agent.failed",
                code="HOST_AGENT_TIMEOUT",
                retryable=True,
                usage=make_usage("internal_error"),
            )

        failed_without_usage = HostAgentFailed(
            type="agent.failed",
            code="HOST_AGENT_INTERNAL_ERROR",
            retryable=False,
        )
        self.assertIsNone(failed_without_usage.usage)

    def test_exported_host_agent_schemas_preserve_union_and_null_tokens(self) -> None:
        schemas = rendered_schemas()
        self.assertIn("host-agent-context.schema.json", schemas)
        self.assertIn("host-agent-usage.schema.json", schemas)
        self.assertIn("host-agent-event.schema.json", schemas)

        context_schema = json.loads(schemas["host-agent-context.schema.json"])
        self.assertFalse(context_schema["additionalProperties"])
        self.assertEqual(
            set(context_schema["properties"]),
            {"player_input", "player_view"},
        )

        usage_schema = json.loads(schemas["host-agent-usage.schema.json"])
        self.assertIsNone(usage_schema["properties"]["input_tokens"]["default"])
        self.assertIsNone(usage_schema["properties"]["output_tokens"]["default"])

        event_schema = json.loads(schemas["host-agent-event.schema.json"])
        self.assertEqual(event_schema["title"], "HostAgentEvent")
        self.assertEqual(event_schema["discriminator"]["propertyName"], "type")
        self.assertEqual(len(event_schema["oneOf"]), 4)
        for event_name in (
            "HostAgentToolStarted",
            "HostAgentToolCompleted",
            "HostAgentCompleted",
            "HostAgentFailed",
        ):
            with self.subTest(event_name=event_name):
                self.assertIn("type", event_schema["$defs"][event_name]["required"])


class FakeHostAgentTests(
    HostAgentPortContractMixin,
    unittest.IsolatedAsyncioTestCase,
):
    def setUp(self) -> None:
        self.context = HostAgentContext(
            player_input=PlayerInput(
                room_id="room_001",
                player_id="player_001",
                actor_id="actor_001",
                client_action_id="action_001",
                utterance="检查书架",
            ),
            player_view=PlayerView(
                room_id="room_001",
                player_id="player_001",
                actor_id="actor_001",
                scene_id="library",
                phase="playing",
                revision="7",
            ),
        )

    async def test_fake_emits_tool_progress_then_completed(self) -> None:
        agent = FakeHostAgent(
            HostAgentCompleted(
                type="agent.completed",
                raw_output=RAW_INTENT_CANDIDATE,
                usage=make_usage(),
            )
        )
        self.assertIsInstance(agent, HostAgentPort)

        events = await self.assert_host_agent_port_contract(agent, self.context)
        self.assertEqual(
            [event.type for event in events],
            ["tool.started", "tool.completed", "agent.completed"],
        )
        self.assertEqual(events[0].call_id, events[1].call_id)
        self.assertEqual(events[0].tool_name, events[1].tool_name)
        self.assertEqual(events[1].status, "success")
        self.assertEqual(events[2].raw_output, RAW_INTENT_CANDIDATE)

    async def test_fake_emits_failure_as_its_only_terminal_event(self) -> None:
        agent = FakeHostAgent(
            HostAgentFailed(
                type="agent.failed",
                code="HOST_AGENT_TIMEOUT",
                retryable=True,
                usage=make_usage("timeout"),
            ),
            tool_status="error",
        )

        events = await self.assert_host_agent_port_contract(agent, self.context)
        self.assertEqual(
            [event.type for event in events],
            ["tool.started", "tool.completed", "agent.failed"],
        )
        self.assertEqual(events[1].status, "error")
        self.assertTrue(events[2].retryable)

    async def test_fake_supports_a_zero_tool_completion(self) -> None:
        terminal: HostAgentTerminalEvent = HostAgentCompleted(
            type="agent.completed",
            raw_output=RAW_INTENT_CANDIDATE,
            usage=make_usage(tool_calls=0),
        )
        agent = FakeHostAgent(terminal, tool_name=None)

        events = await self.assert_host_agent_port_contract(agent, self.context)
        self.assertEqual(events, (terminal,))

    async def test_fake_rejects_a_non_terminal_final_event(self) -> None:
        with self.assertRaisesRegex(TypeError, "terminal_event"):
            FakeHostAgent(
                HostAgentToolStarted(
                    type="tool.started",
                    call_id="call_001",
                    tool_name="visible_lookup",
                )
            )


if __name__ == "__main__":
    unittest.main()
