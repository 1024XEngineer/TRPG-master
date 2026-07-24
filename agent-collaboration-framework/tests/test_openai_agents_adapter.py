from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import logging
from types import SimpleNamespace
from typing import Any
import unittest

from agents.models.interface import Model, ModelResponse
from agents.usage import Usage
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFunctionToolCall,
    ResponseOutputItemDoneEvent,
    ResponseOutputMessage,
    ResponseOutputText,
    ResponseUsage,
)
from pydantic import ValidationError

from collaboration_framework.bootstrap.host_agent import (
    HostAgentConfigurationError,
    build_qwen_host_agent,
)
from collaboration_framework.contracts import PlayerInput, PlayerView, VisibleEntity
from collaboration_framework.host.adapters.openai_agents import (
    QwenHostAgentAdapter,
    QwenHostAgentConfig,
)
from collaboration_framework.host.adapters.openai_agents.adapter import (
    InvalidHostAgentOutput,
    parse_raw_output,
)
from collaboration_framework.host.application.tool_registry import (
    ToolDefinition,
    ToolRegistry,
)
from collaboration_framework.host.schemas import (
    HostAgentCompleted,
    HostAgentContext,
    HostAgentFailed,
    HostAgentToolCompleted,
    HostAgentToolStarted,
    SearchVisibleEntitiesArgs,
    SearchVisibleEntitiesResult,
    VisibleEntitySummary,
)
from collaboration_framework.host.tools import build_player_view_tool_registry
from tests.test_host_agent_contract import HostAgentPortContractMixin


UNKNOWN_INTENT = {
    "kind": "unknown",
    "verb": "unknown",
    "target": {"matched": False, "raw": "不明确的行动"},
    "check": {"route": "none"},
    "summary": "玩家行动不明确",
    "clarification_question": "你想调查哪个目标？",
}
SECRET = "SECRET_SENTINEL_DO_NOT_LEAK"


def make_context(*, utterance: str = "检查红色书架") -> HostAgentContext:
    return HostAgentContext(
        player_input=PlayerInput(
            room_id="room_001",
            player_id="player_001",
            actor_id="actor_001",
            client_action_id="action_001",
            utterance=utterance,
        ),
        player_view=PlayerView(
            room_id="room_001",
            player_id="player_001",
            actor_id="actor_001",
            scene_id="library",
            phase="playing",
            revision="7",
            visible_entities=(
                VisibleEntity(
                    id="entity_dynamic_7f3a",
                    kind="object",
                    name="红色书架",
                    aliases=("书架",),
                    content="一个玩家可见的红色木书架。",
                ),
            ),
        ),
    )


def make_config(**updates: object) -> QwenHostAgentConfig:
    values: dict[str, object] = {
        "api_key": "test-secret-key",
        "max_turns": 6,
        "max_tool_calls": 8,
        "tool_timeout_seconds": 0.2,
        "timeout_seconds": 1,
    }
    values.update(updates)
    return QwenHostAgentConfig(**values)


def final_message(value: object) -> ResponseOutputMessage:
    text = value if isinstance(value, str) else json.dumps(
        value,
        ensure_ascii=False,
    )
    return ResponseOutputMessage(
        id="message_001",
        content=[
            ResponseOutputText(
                annotations=[],
                text=text,
                type="output_text",
            )
        ],
        role="assistant",
        status="completed",
        type="message",
    )


def tool_call(
    name: str,
    arguments: str | dict[str, object],
    *,
    call_id: str,
) -> ResponseFunctionToolCall:
    rendered = (
        arguments
        if isinstance(arguments, str)
        else json.dumps(arguments, ensure_ascii=False)
    )
    return ResponseFunctionToolCall(
        arguments=rendered,
        call_id=call_id,
        name=name,
        type="function_call",
        status="completed",
    )


def response_usage(input_tokens: int, output_tokens: int) -> ResponseUsage:
    return ResponseUsage(
        input_tokens=input_tokens,
        input_tokens_details={"cached_tokens": 0},
        output_tokens=output_tokens,
        output_tokens_details={"reasoning_tokens": 0},
        total_tokens=input_tokens + output_tokens,
    )


def sdk_response(
    output: list[ResponseFunctionToolCall | ResponseOutputMessage],
    *,
    response_id: str,
    usage: ResponseUsage | None = None,
) -> Response:
    return Response(
        id=response_id,
        created_at=0,
        model="scripted-qwen",
        object="response",
        output=output,
        parallel_tool_calls=False,
        temperature=0,
        tool_choice="auto",
        tools=[],
        top_p=1,
        status="completed",
        usage=usage,
    )


def tool_outputs(model_input: object) -> list[dict[str, object]]:
    if not isinstance(model_input, list):
        return []
    outputs: list[dict[str, object]] = []
    for item in model_input:
        if not isinstance(item, dict) or item.get("type") != "function_call_output":
            continue
        raw_output = item.get("output")
        if not isinstance(raw_output, str):
            continue
        decoded = json.loads(raw_output)
        if isinstance(decoded, dict):
            outputs.append(decoded)
    return outputs


class ScriptedStreamingModel(Model):
    def __init__(
        self,
        responder: Callable[[object, int], Response],
    ) -> None:
        self._responder = responder
        self.calls: list[dict[str, object]] = []

    async def get_response(self, *args: Any, **kwargs: Any) -> ModelResponse:
        model_input = args[1]
        response = self._responder(model_input, len(self.calls) + 1)
        usage = response.usage
        return ModelResponse(
            output=response.output,
            usage=Usage(
                requests=1 if usage is not None else 0,
                input_tokens=usage.input_tokens if usage else 0,
                output_tokens=usage.output_tokens if usage else 0,
                total_tokens=usage.total_tokens if usage else 0,
            ),
            response_id=response.id,
        )

    async def stream_response(
        self,
        system_instructions: str | None,
        model_input: object,
        model_settings: object,
        tools: list[object],
        _output_schema: object,
        _handoffs: list[object],
        tracing: object,
        **_kwargs: object,
    ):
        self.calls.append(
            {
                "system_instructions": system_instructions,
                "input": model_input,
                "model_settings": model_settings,
                "tools": tools,
                "tracing": tracing,
            }
        )
        response = self._responder(model_input, len(self.calls))
        sequence_number = 0
        for index, item in enumerate(response.output):
            if not isinstance(item, ResponseFunctionToolCall):
                continue
            yield ResponseOutputItemDoneEvent(
                item=item,
                output_index=index,
                sequence_number=sequence_number,
                type="response.output_item.done",
            )
            sequence_number += 1
        yield ResponseCompletedEvent(
            response=response,
            sequence_number=sequence_number,
            type="response.completed",
        )


class BlockingStreamingModel(Model):
    async def get_response(self, *args: Any, **kwargs: Any) -> ModelResponse:
        raise AssertionError("streaming adapter must not call get_response")

    async def stream_response(self, *args: Any, **kwargs: Any):
        await asyncio.sleep(10)
        if False:
            yield None


def make_adapter(
    model: Model,
    *,
    config: QwenHostAgentConfig | None = None,
    registry: ToolRegistry | None = None,
) -> QwenHostAgentAdapter:
    return QwenHostAgentAdapter(
        model=model,
        tool_registry=registry or build_player_view_tool_registry(),
        config=config or make_config(),
    )


async def collect(adapter: QwenHostAgentAdapter) -> tuple[object, ...]:
    return tuple([event async for event in adapter.astream(make_context())])


def terminal(events: tuple[object, ...]) -> HostAgentCompleted | HostAgentFailed:
    value = events[-1]
    if not isinstance(value, (HostAgentCompleted, HostAgentFailed)):
        raise AssertionError("missing terminal Host Agent event")
    return value


class QwenConfigAndBootstrapTests(unittest.TestCase):
    def test_config_masks_key_and_validates_provider_settings(self) -> None:
        config = make_config(api_key=SECRET)
        self.assertNotIn(SECRET, repr(config))
        self.assertEqual(config.model, "qwen-plus")
        self.assertEqual(
            config.base_url,
            "https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

        invalid_updates = (
            {"api_key": " "},
            {"base_url": "file:///tmp/provider"},
            {"model": " "},
            {"max_turns": 0},
            {"max_tool_calls": 0},
            {"tool_timeout_seconds": 0},
            {"timeout_seconds": 0},
        )
        for updates in invalid_updates:
            with self.subTest(updates=updates):
                with self.assertRaises(ValidationError):
                    make_config(**updates)

    def test_bootstrap_requires_safe_explicit_configuration(self) -> None:
        with self.assertRaisesRegex(
            HostAgentConfigurationError,
            "HOST_AGENT_API_KEY is required",
        ):
            build_qwen_host_agent({})

        secret_stream = StringIO()
        with redirect_stdout(secret_stream), redirect_stderr(secret_stream):
            with self.assertRaisesRegex(
                HostAgentConfigurationError,
                "configuration is invalid",
            ):
                build_qwen_host_agent(
                    {
                        "HOST_AGENT_API_KEY": SECRET,
                        "HOST_AGENT_MAX_TURNS": "not-an-int",
                    }
                )
        self.assertNotIn(SECRET, secret_stream.getvalue())

    def test_bootstrap_builds_adapter_without_network_access(self) -> None:
        adapter = build_qwen_host_agent(
            {
                "HOST_AGENT_API_KEY": SECRET,
                "HOST_AGENT_BASE_URL": "https://provider.example/v1/",
                "HOST_AGENT_MODEL": "qwen-test",
                "HOST_AGENT_MAX_TURNS": "3",
                "HOST_AGENT_MAX_TOOL_CALLS": "4",
                "HOST_AGENT_TOOL_TIMEOUT_SECONDS": "1.5",
                "HOST_AGENT_TIMEOUT_SECONDS": "9",
            }
        )
        self.assertIsInstance(adapter, QwenHostAgentAdapter)
        self.assertNotIn(SECRET, repr(adapter))


class RawOutputTests(unittest.TestCase):
    def test_accepts_only_plain_finite_json_objects(self) -> None:
        self.assertEqual(parse_raw_output('{"kind":"unknown"}'), {"kind": "unknown"})
        self.assertEqual(parse_raw_output({"count": 0}), {"count": 0})

        invalid_values = (
            "not-json",
            "```json\n{}\n```",
            "[]",
            "NaN",
            '{"score": NaN}',
            ["not", "an", "object"],
            {"score": float("nan")},
            SimpleNamespace(value={}),
        )
        for value in invalid_values:
            with self.subTest(value=value):
                with self.assertRaises(InvalidHostAgentOutput):
                    parse_raw_output(value)


class QwenHostAgentAdapterTests(
    HostAgentPortContractMixin,
    unittest.IsolatedAsyncioTestCase,
):
    async def test_direct_final_uses_real_runner_and_safe_settings(self) -> None:
        model = ScriptedStreamingModel(
            lambda _input, _round: sdk_response(
                [final_message(UNKNOWN_INTENT)],
                response_id="response_direct",
                usage=response_usage(11, 3),
            )
        )
        adapter = make_adapter(model)

        events = await self.assert_host_agent_port_contract(
            adapter,
            make_context(),
        )

        self.assertEqual([event.type for event in events], ["agent.completed"])
        completed = events[0]
        self.assertIsInstance(completed, HostAgentCompleted)
        self.assertEqual(completed.raw_output, UNKNOWN_INTENT)
        self.assertEqual(completed.usage.model_rounds, 1)
        self.assertEqual(completed.usage.tool_calls, 0)
        self.assertEqual(completed.usage.input_tokens, 11)
        self.assertEqual(completed.usage.output_tokens, 3)

        call = model.calls[0]
        settings = call["model_settings"]
        self.assertEqual(settings.temperature, 0)
        self.assertFalse(settings.parallel_tool_calls)
        self.assertTrue(settings.include_usage)
        self.assertEqual(settings.extra_body, {"enable_thinking": False})
        self.assertEqual(settings.tool_choice, "auto")
        self.assertIn("trpg-host-intent-v1", call["system_instructions"])
        self.assertNotIn("GameState", call["input"])
        self.assertNotIn("ModuleContent", call["input"])
        self.assertFalse(call["tracing"].include_data())

    async def test_single_tool_call_round_trips_safe_result(self) -> None:
        observed_outputs: list[dict[str, object]] = []

        def respond(model_input: object, round_number: int) -> Response:
            if round_number == 1:
                return sdk_response(
                    [
                        tool_call(
                            "search_visible_entities",
                            {"query": "书架"},
                            call_id="call_search",
                        )
                    ],
                    response_id="response_search",
                    usage=response_usage(10, 2),
                )
            observed_outputs.extend(tool_outputs(model_input))
            return sdk_response(
                [final_message(UNKNOWN_INTENT)],
                response_id="response_final",
                usage=response_usage(12, 4),
            )

        events = await collect(make_adapter(ScriptedStreamingModel(respond)))

        self.assertEqual(
            [event.type for event in events],
            ["tool.started", "tool.completed", "agent.completed"],
        )
        self.assertEqual(events[0].call_id, "call_search")
        self.assertEqual(events[1].status, "success")
        self.assertEqual(
            observed_outputs[0]["matches"][0]["id"],
            "entity_dynamic_7f3a",
        )
        completed = terminal(events)
        self.assertIsInstance(completed, HostAgentCompleted)
        self.assertEqual(completed.usage.model_rounds, 2)
        self.assertEqual(completed.usage.tool_calls, 1)
        self.assertEqual(completed.usage.input_tokens, 22)
        self.assertEqual(completed.usage.output_tokens, 6)

    async def test_second_tool_id_is_derived_from_first_tool_result(self) -> None:
        derived_ids: list[str] = []

        def respond(model_input: object, round_number: int) -> Response:
            if round_number == 1:
                return sdk_response(
                    [
                        tool_call(
                            "search_visible_entities",
                            {"query": "红色书架"},
                            call_id="call_search",
                        )
                    ],
                    response_id="response_1",
                    usage=response_usage(7, 1),
                )
            if round_number == 2:
                search_output = tool_outputs(model_input)[-1]
                entity_id = search_output["matches"][0]["id"]
                derived_ids.append(entity_id)
                return sdk_response(
                    [
                        tool_call(
                            "get_visible_entity",
                            {"entity_id": entity_id},
                            call_id="call_get",
                        )
                    ],
                    response_id="response_2",
                    usage=response_usage(8, 1),
                )
            entity_output = tool_outputs(model_input)[-1]
            derived_ids.append(entity_output["id"])
            final_intent = {
                "kind": "action",
                "verb": "inspect",
                "target": {
                    "matched": True,
                    "id": entity_output["id"],
                },
                "check": {"route": "none"},
                "summary": "检查红色书架",
            }
            return sdk_response(
                [final_message(final_intent)],
                response_id="response_3",
                usage=response_usage(9, 2),
            )

        events = await collect(make_adapter(ScriptedStreamingModel(respond)))

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
        self.assertEqual(
            [event.tool_name for event in events[:-1]],
            [
                "search_visible_entities",
                "search_visible_entities",
                "get_visible_entity",
                "get_visible_entity",
            ],
        )
        self.assertEqual(
            derived_ids,
            ["entity_dynamic_7f3a", "entity_dynamic_7f3a"],
        )
        completed = terminal(events)
        self.assertIsInstance(completed, HostAgentCompleted)
        self.assertEqual(
            completed.raw_output["target"]["id"],
            "entity_dynamic_7f3a",
        )
        self.assertEqual(completed.usage.model_rounds, 3)
        self.assertEqual(completed.usage.tool_calls, 2)

    async def test_invalid_arguments_are_safe_and_recoverable(self) -> None:
        recovered_errors: list[dict[str, object]] = []

        def respond(model_input: object, round_number: int) -> Response:
            if round_number == 1:
                return sdk_response(
                    [
                        tool_call(
                            "search_visible_entities",
                            "not-json",
                            call_id="call_invalid",
                        )
                    ],
                    response_id="response_invalid",
                )
            recovered_errors.extend(tool_outputs(model_input))
            return sdk_response(
                [final_message(UNKNOWN_INTENT)],
                response_id="response_recovered",
            )

        events = await collect(make_adapter(ScriptedStreamingModel(respond)))

        self.assertEqual(events[1].status, "error")
        self.assertEqual(
            recovered_errors[0]["error"]["code"],
            "INVALID_TOOL_ARGUMENTS",
        )
        self.assertIsInstance(terminal(events), HostAgentCompleted)

    async def test_invisible_entity_error_is_safe_and_recoverable(self) -> None:
        recovered_errors: list[dict[str, object]] = []

        def respond(model_input: object, round_number: int) -> Response:
            if round_number == 1:
                return sdk_response(
                    [
                        tool_call(
                            "get_visible_entity",
                            {"entity_id": "hidden_or_missing"},
                            call_id="call_invisible",
                        )
                    ],
                    response_id="response_invisible",
                )
            recovered_errors.extend(tool_outputs(model_input))
            return sdk_response(
                [final_message(UNKNOWN_INTENT)],
                response_id="response_after_invisible",
            )

        events = await collect(make_adapter(ScriptedStreamingModel(respond)))

        self.assertEqual(events[1].status, "error")
        self.assertEqual(
            recovered_errors[0]["error"]["code"],
            "ENTITY_NOT_VISIBLE",
        )
        self.assertIsInstance(terminal(events), HostAgentCompleted)

    async def test_tool_internal_error_is_safe_and_recoverable(self) -> None:
        recovered_errors: list[dict[str, object]] = []

        async def failing_handler(
            _context: HostAgentContext,
            _arguments: SearchVisibleEntitiesArgs,
        ) -> SearchVisibleEntitiesResult:
            raise RuntimeError(f"tool failure {SECRET}")

        registry = ToolRegistry(
            (
                ToolDefinition(
                    name="failing_search",
                    description="A deliberately failing read-only search.",
                    args_model=SearchVisibleEntitiesArgs,
                    result_model=SearchVisibleEntitiesResult,
                    public_progress_label="正在执行失败测试",
                    handler=failing_handler,
                ),
            )
        )

        def respond(model_input: object, round_number: int) -> Response:
            if round_number == 1:
                return sdk_response(
                    [
                        tool_call(
                            "failing_search",
                            {"query": "书架"},
                            call_id="call_failing",
                        )
                    ],
                    response_id="response_failing",
                )
            recovered_errors.extend(tool_outputs(model_input))
            return sdk_response(
                [final_message(UNKNOWN_INTENT)],
                response_id="response_after_failure",
            )

        events = await collect(
            make_adapter(
                ScriptedStreamingModel(respond),
                registry=registry,
            )
        )

        self.assertEqual(events[1].status, "error")
        self.assertEqual(
            recovered_errors[0]["error"]["code"],
            "TOOL_INTERNAL_ERROR",
        )
        self.assertNotIn(SECRET, json.dumps(recovered_errors))
        self.assertIsInstance(terminal(events), HostAgentCompleted)

    async def test_tool_timeout_is_safe_and_recoverable(self) -> None:
        timeout_results: list[dict[str, object]] = []

        async def slow_handler(
            _context: HostAgentContext,
            _arguments: SearchVisibleEntitiesArgs,
        ) -> SearchVisibleEntitiesResult:
            await asyncio.sleep(1)
            return SearchVisibleEntitiesResult()

        registry = ToolRegistry(
            (
                ToolDefinition(
                    name="slow_search",
                    description="A deliberately slow read-only search.",
                    args_model=SearchVisibleEntitiesArgs,
                    result_model=SearchVisibleEntitiesResult,
                    public_progress_label="正在执行慢速搜索",
                    handler=slow_handler,
                ),
            )
        )

        def respond(model_input: object, round_number: int) -> Response:
            if round_number == 1:
                return sdk_response(
                    [
                        tool_call(
                            "slow_search",
                            {"query": "书架"},
                            call_id="call_slow",
                        )
                    ],
                    response_id="response_slow",
                )
            timeout_results.extend(tool_outputs(model_input))
            return sdk_response(
                [final_message(UNKNOWN_INTENT)],
                response_id="response_after_timeout",
            )

        adapter = make_adapter(
            ScriptedStreamingModel(respond),
            config=make_config(tool_timeout_seconds=0.01),
            registry=registry,
        )
        events = await collect(adapter)

        self.assertEqual(events[1].status, "error")
        self.assertEqual(
            timeout_results[0]["error"]["code"],
            "TOOL_TIMEOUT",
        )
        self.assertIsInstance(terminal(events), HostAgentCompleted)

    async def test_tool_budget_stops_before_ninth_registry_invocation(self) -> None:
        invocations = 0

        async def counting_handler(
            _context: HostAgentContext,
            _arguments: SearchVisibleEntitiesArgs,
        ) -> SearchVisibleEntitiesResult:
            nonlocal invocations
            invocations += 1
            return SearchVisibleEntitiesResult(
                matches=(
                    VisibleEntitySummary(
                        id="entity_dynamic_7f3a",
                        kind="object",
                        name="红色书架",
                    ),
                )
            )

        registry = ToolRegistry(
            (
                ToolDefinition(
                    name="counted_search",
                    description="Count a safe search invocation.",
                    args_model=SearchVisibleEntitiesArgs,
                    result_model=SearchVisibleEntitiesResult,
                    public_progress_label="正在计数搜索",
                    handler=counting_handler,
                ),
            )
        )
        model = ScriptedStreamingModel(
            lambda _input, round_number: sdk_response(
                [
                    tool_call(
                        "counted_search",
                        {"query": "书架"},
                        call_id=f"call_{round_number}",
                    )
                ],
                response_id=f"response_{round_number}",
            )
        )
        adapter = make_adapter(
            model,
            config=make_config(max_turns=20, max_tool_calls=8),
            registry=registry,
        )

        events = await collect(adapter)

        self.assertEqual(invocations, 8)
        failed = terminal(events)
        self.assertIsInstance(failed, HostAgentFailed)
        self.assertEqual(
            failed.code,
            "HOST_AGENT_TOOL_BUDGET_EXCEEDED",
        )
        self.assertEqual(failed.usage.termination_reason, "tool_budget_exceeded")
        self.assertEqual(failed.usage.tool_calls, 9)
        starts = [event for event in events if isinstance(event, HostAgentToolStarted)]
        finishes = [
            event for event in events if isinstance(event, HostAgentToolCompleted)
        ]
        self.assertEqual(len(starts), len(finishes))
        self.assertEqual(
            {event.call_id for event in starts},
            {event.call_id for event in finishes},
        )

    async def test_max_turns_maps_to_one_failed_terminal(self) -> None:
        model = ScriptedStreamingModel(
            lambda _input, round_number: sdk_response(
                [
                    tool_call(
                        "search_visible_entities",
                        {"query": "书架"},
                        call_id=f"call_repeat_{round_number}",
                    )
                ],
                response_id=f"response_repeat_{round_number}",
            )
        )
        adapter = make_adapter(
            model,
            config=make_config(max_turns=1),
        )

        events = await collect(adapter)

        failed = terminal(events)
        self.assertIsInstance(failed, HostAgentFailed)
        self.assertEqual(failed.code, "HOST_AGENT_MAX_TURNS")
        self.assertFalse(failed.retryable)
        self.assertEqual(failed.usage.termination_reason, "max_turns")
        self.assertEqual(sum(isinstance(e, HostAgentFailed) for e in events), 1)

    async def test_overall_timeout_cancels_and_is_retryable(self) -> None:
        adapter = make_adapter(
            BlockingStreamingModel(),
            config=make_config(timeout_seconds=0.01),
        )

        events = await collect(adapter)

        self.assertEqual(len(events), 1)
        failed = terminal(events)
        self.assertIsInstance(failed, HostAgentFailed)
        self.assertEqual(failed.code, "HOST_AGENT_TIMEOUT")
        self.assertTrue(failed.retryable)
        self.assertEqual(failed.usage.termination_reason, "timeout")

    async def test_unknown_tool_fails_closed_without_registry_call(self) -> None:
        model = ScriptedStreamingModel(
            lambda _input, _round: sdk_response(
                [
                    tool_call(
                        "unregistered_tool",
                        {},
                        call_id="call_unknown",
                    )
                ],
                response_id="response_unknown",
            )
        )

        events = await collect(make_adapter(model))

        failed = terminal(events)
        self.assertIsInstance(failed, HostAgentFailed)
        self.assertEqual(failed.code, "HOST_AGENT_INTERNAL_ERROR")
        self.assertFalse(failed.retryable)

    async def test_provider_exception_fails_closed_without_leaking(self) -> None:
        def fail_provider(_input: object, _round: int) -> Response:
            raise RuntimeError(f"provider failure {SECRET}")

        stream = StringIO()
        handler = logging.StreamHandler(stream)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            events = await collect(
                make_adapter(ScriptedStreamingModel(fail_provider))
            )
        finally:
            root_logger.removeHandler(handler)

        failed = terminal(events)
        self.assertIsInstance(failed, HostAgentFailed)
        self.assertEqual(failed.code, "HOST_AGENT_INTERNAL_ERROR")
        self.assertFalse(failed.retryable)
        self.assertNotIn(SECRET, json.dumps(failed.to_json_dict()))
        self.assertNotIn(SECRET, stream.getvalue())

    async def test_malformed_sdk_event_fails_closed(self) -> None:
        malformed_call = ResponseFunctionToolCall.model_construct(
            arguments="{}",
            call_id="",
            name="search_visible_entities",
            type="function_call",
            status="completed",
        )
        model = ScriptedStreamingModel(
            lambda _input, _round: sdk_response(
                [malformed_call],
                response_id="response_malformed",
            )
        )

        events = await collect(make_adapter(model))

        failed = terminal(events)
        self.assertIsInstance(failed, HostAgentFailed)
        self.assertEqual(failed.code, "HOST_AGENT_INTERNAL_ERROR")
        self.assertFalse(failed.retryable)

    async def test_invalid_final_outputs_map_to_stable_failure(self) -> None:
        invalid_outputs = (
            "not-json",
            "[]",
            "```json\n{}\n```",
            '{"score":NaN}',
        )
        for value in invalid_outputs:
            with self.subTest(value=value):
                model = ScriptedStreamingModel(
                    lambda _input, _round, _value=value: sdk_response(
                        [final_message(_value)],
                        response_id="response_invalid_final",
                    )
                )
                events = await collect(make_adapter(model))
                failed = terminal(events)
                self.assertIsInstance(failed, HostAgentFailed)
                self.assertEqual(failed.code, "HOST_AGENT_INVALID_OUTPUT")
                self.assertEqual(
                    failed.usage.termination_reason,
                    "invalid_output",
                )

    async def test_usage_preserves_zero_and_rejects_partial_reporting(self) -> None:
        zero_model = ScriptedStreamingModel(
            lambda _input, _round: sdk_response(
                [final_message(UNKNOWN_INTENT)],
                response_id="response_zero",
                usage=response_usage(0, 0),
            )
        )
        zero_events = await collect(make_adapter(zero_model))
        zero_completed = terminal(zero_events)
        self.assertIsInstance(zero_completed, HostAgentCompleted)
        self.assertEqual(zero_completed.usage.input_tokens, 0)
        self.assertEqual(zero_completed.usage.output_tokens, 0)

        def partial_response(model_input: object, round_number: int) -> Response:
            if round_number == 1:
                return sdk_response(
                    [
                        tool_call(
                            "search_visible_entities",
                            {"query": "书架"},
                            call_id="call_partial",
                        )
                    ],
                    response_id="response_reported",
                    usage=response_usage(8, 1),
                )
            self.assertTrue(tool_outputs(model_input))
            return sdk_response(
                [final_message(UNKNOWN_INTENT)],
                response_id="response_unreported",
                usage=None,
            )

        partial_events = await collect(
            make_adapter(ScriptedStreamingModel(partial_response))
        )
        partial_completed = terminal(partial_events)
        self.assertIsInstance(partial_completed, HostAgentCompleted)
        self.assertIsNone(partial_completed.usage.input_tokens)
        self.assertIsNone(partial_completed.usage.output_tokens)

    async def test_events_and_default_logs_exclude_sensitive_data(self) -> None:
        context = make_context(utterance=f"检查 {SECRET}")
        model = ScriptedStreamingModel(
            lambda _input, _round: sdk_response(
                [final_message(UNKNOWN_INTENT)],
                response_id="response_secret",
            )
        )
        stream = StringIO()
        handler = logging.StreamHandler(stream)
        root_logger = logging.getLogger()
        root_logger.addHandler(handler)
        try:
            events = tuple(
                [event async for event in make_adapter(model).astream(context)]
            )
        finally:
            root_logger.removeHandler(handler)

        rendered = json.dumps(
            [
                event.to_json_dict()
                for event in events
                if isinstance(
                    event,
                    (
                        HostAgentToolStarted,
                        HostAgentToolCompleted,
                        HostAgentCompleted,
                        HostAgentFailed,
                    ),
                )
            ],
            ensure_ascii=False,
        )
        self.assertNotIn(SECRET, rendered)
        self.assertNotIn(SECRET, stream.getvalue())


if __name__ == "__main__":
    unittest.main()
