from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import anyio
import httpx
import pytest
from collaboration_framework.contracts import (
    ActionAdjudication,
    ActionPlan,
    ActionPlanStep,
    Intent,
    ModuleContentV3,
    PlayerInput,
    PlayerView,
    SceneView,
    SelfActorView,
    SingleActionDecision,
)
from collaboration_framework.engine import (
    ActorResources,
    ActorState,
    AdjudicationEngineService,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
)
from collaboration_framework.host.application import PlayerViewProjector, TurnExecutionError
from collaboration_framework.host.ports import ActionPlanStepFailure
from collaboration_framework.host.schemas import (
    ActionPlanStepContext,
    HostAgentContext,
    RecentTurn,
    RecentTurnContext,
    TurnPlanningContext,
    VisibleHistoryText,
)
from pydantic import ValidationError
from structlog.testing import capture_logs

from app.adapters.deepseek_models import DeepSeekChatCompletionsJsonClient
from app.adapters.openai_models import (
    _ACTION_PLAN_NARRATION_INSTRUCTIONS,
    _OPENING_NARRATION_INSTRUCTIONS,
    OpenAIResponsesJsonClient,
    PromptActionPlanStepAdjudicator,
    PromptHostTurnDecisionModel,
    PromptTurnPlanner,
)
from app.adapters.qwen_models import QwenChatCompletionsJsonClient
from app.adapters.structured_http import (
    ModelClientRetryPolicy,
    StructuredOutputError,
    is_transient_model_error,
)
from app.core.action_plan_turn import (
    build_action_plan_turn_application,
    semantic_planner_required,
    semantic_planner_selected,
)
from app.core.config import Settings, model_client_retry_policy
from app.core.turn import _configured_opening_models
from app.service.character_background import build_character_background_service
from app.service.portrait_generation import build_portrait_generation_service

ROOT = Path(__file__).resolve().parents[2]


def test_action_plan_narration_uses_final_post_roll_outcome() -> None:
    """叙事不能把消耗幸运或强推之前的失败当成最终结果。"""

    assert "消耗幸运" in _ACTION_PLAN_NARRATION_INSTRUCTIONS
    assert "outcome=success" in _ACTION_PLAN_NARRATION_INSTRUCTIONS
    assert "最终权威结果" in _ACTION_PLAN_NARRATION_INSTRUCTIONS


def test_semantic_planner_rollout_bucket_is_stable() -> None:
    first = semantic_planner_selected(
        room_id="room-1",
        client_action_id="action-1",
        rollout_percent=25,
    )
    assert (
        semantic_planner_selected(
            room_id="room-1",
            client_action_id="action-1",
            rollout_percent=25,
        )
        is first
    )
    assert not semantic_planner_selected(
        room_id="room-1", client_action_id="action-1", rollout_percent=0
    )
    assert semantic_planner_selected(
        room_id="room-1", client_action_id="action-1", rollout_percent=100
    )


@pytest.mark.parametrize(
    ("utterance", "reason"),
    [
        ("观察当前房间", "explicit_single_step"),
        ("仔细检查书架上的文件", "semantic_uncertainty_marker"),
        ("先观察房间，然后询问眼前的人", "multi_step_marker"),
        ("观察房间和窗户", "multi_target_marker"),
    ],
)
def test_semantic_planner_route_preserves_fast_path_for_clear_single_steps(
    utterance: str,
    reason: str,
) -> None:
    required, actual_reason = semantic_planner_required(utterance)

    assert actual_reason == reason
    assert required is (reason != "explicit_single_step")


def test_semantic_planner_rollout_requires_independent_configuration() -> None:
    with pytest.raises(ValidationError, match="TURN_PLANNER_PROVIDER"):
        Settings(host_model_provider="fake", turn_planner_rollout_percent=1)
    settings = Settings(
        host_model_provider="fake",
        turn_planner_provider="fake",
        turn_planner_rollout_percent=100,
    )
    assert settings.turn_planner_rollout_percent == 100


def test_action_plan_narration_requires_named_actor_in_multiplayer() -> None:
    assert "addressing_mode=named_actor" in _ACTION_PLAN_NARRATION_INSTRUCTIONS
    assert "acting_character_name" in _ACTION_PLAN_NARRATION_INSTRUCTIONS
    assert "对白中的第二人称合法" in _ACTION_PLAN_NARRATION_INSTRUCTIONS


def test_opening_narration_mentions_named_actor_mode() -> None:
    assert "addressing_mode 为 named_actor" in _OPENING_NARRATION_INSTRUCTIONS


def test_action_plan_narration_preserves_completed_travel_before_clarification() -> None:
    assert "completed_steps 已有成功的旅行步骤" in (_ACTION_PLAN_NARRATION_INSTRUCTIONS)
    assert "绝不得说\n该地点没找到" in _ACTION_PLAN_NARRATION_INSTRUCTIONS


def test_action_plan_narration_forbids_repeating_previous_atmosphere() -> None:
    assert "previous_published_narration" in _ACTION_PLAN_NARRATION_INSTRUCTIONS
    assert "不得用相同或几乎相同的环境开场重铺" in _ACTION_PLAN_NARRATION_INSTRUCTIONS
    assert "不要再写一整段地点简介" in _ACTION_PLAN_NARRATION_INSTRUCTIONS


def load_paper_chase() -> ModuleContentV3:
    examples = (
        ROOT
        / "agent-collaboration-framework"
        / "docs"
        / "module-parser"
        / "examples"
        / "module-content-validation"
    )
    for path in examples.rglob("module-content-v3.json"):
        payload = path.read_text(encoding="utf-8")
        if '"module_id": "paper-chase-zh-coc7"' in payload:
            return ModuleContentV3.model_validate_json(payload)
    raise AssertionError("Paper Chase ModuleContentV3 fixture was not found")


def conversation_state(module: ModuleContentV3) -> GameState:
    """站在地穴里，面前是一个愿意开口的人影——这里要的是一个能对话的场面。"""

    entities = {entity.id: dict(entity.state) for entity in module.entities}
    entities["cemetery_figure"]["willing_to_talk"] = True
    return GameState(
        room_id="room_llm",
        scene_id="crypt",
        actors={
            "actor_1": ActorState(
                player_id="player_1",
                name="Investigator",
                source_character_id="character_1",
                source_character_version=1,
                state={"attributes": {}, "derived_stats": {}, "skills": {}},
                resources=ActorResources(hp=10, san=60, mp=10, luck=50),
            )
        },
        entities=entities,
    )


class ScriptedTurnDecisionClient:
    async def generate(self, *, schema_name, schema, instructions, input_payload):
        assert schema_name == "trpg_host_turn_decision"
        assert schema and "32 步" in instructions
        utterance = input_payload["player_input"]["utterance"]
        requested = int(utterance.split(":", 1)[1])
        if requested == 1:
            return {
                "kind": "single_action",
                "adjudication": {
                    "request_id": "model-value",
                    "source_revision": "model-value",
                    "actor_id": "model-value",
                    "summary": "观察当前场景",
                    "target": {"kind": "location", "id": "conversation"},
                    "method": {"family": "action", "description": "观察"},
                    "check": {"mode": "none", "candidates": []},
                    "success_effects": [{"type": "narrative_only"}],
                    "failure_effects": [],
                },
            }
        return {
            "kind": "action_plan",
            "goal": utterance,
            "steps": [
                {"kind": "action", "semantic_goal": f"完成步骤 {index + 1}"}
                for index in range(requested)
            ],
        }


class SequencedTurnDecisionClient:
    """依次返回预设规划结果，用于验证坏结构只重试一次。"""

    def __init__(self, results: list[dict]) -> None:
        self.results = results
        self.calls = 0

    async def generate(self, **kwargs) -> dict:
        del kwargs
        result = self.results[self.calls]
        self.calls += 1
        return result


@pytest.mark.parametrize("step_count", [1, 2, 3, 4, 5])
async def test_prompt_turn_decision_accepts_single_and_variable_plan_lengths(
    step_count: int,
) -> None:
    module = load_paper_chase()
    state = conversation_state(module)
    store = InMemoryEngineStore()
    store.register_room(module_content=module, initial_state=state)
    player_input = PlayerInput(
        room_id=state.room_id,
        player_id="player_1",
        actor_id="actor_1",
        client_action_id=f"decision-{step_count}",
        utterance=f"steps:{step_count}",
    )
    view = await PlayerViewProjector(RuleEngineService(store)).project(player_input)
    decision = await PromptHostTurnDecisionModel(ScriptedTurnDecisionClient()).generate(
        HostAgentContext(
            player_input=player_input,
            player_view=view,
            recent_history=RecentTurnContext.empty(
                player_input=player_input,
                player_view=view,
            ),
        )
    )

    if step_count == 1:
        assert isinstance(decision, SingleActionDecision)
    else:
        assert isinstance(decision, ActionPlan)
        assert len(decision.steps) == step_count


def _valid_travel_decision() -> dict:
    """构造一个符合 HostTurnDecision 契约的旅行结果。"""

    return {
        "kind": "single_action",
        "adjudication": {
            "request_id": "model-value",
            "source_revision": "revision-1",
            "actor_id": "actor-1",
            "summary": "去墓地",
            "target": {"kind": "location", "id": "cemetery"},
            "method": {"family": "travel", "description": "去墓地"},
            "persistence_intent": "location",
            "check": {"mode": "none", "candidates": []},
            "success_effects": [{"type": "enter_location", "location_id": "cemetery"}],
            "failure_effects": [],
        },
    }


async def test_turn_planner_retries_schema_failure_once_then_succeeds() -> None:
    """首次结构损坏不应直接终止回合，第二份合法结果应正常使用。"""

    client = SequencedTurnDecisionClient([{"kind": "single_action"}, _valid_travel_decision()])
    context = cast(HostAgentContext, SimpleNamespace(to_json_dict=lambda: {}))

    decision = await PromptHostTurnDecisionModel(client).generate(context)

    assert isinstance(decision, SingleActionDecision)
    assert client.calls == 2


async def test_turn_planner_classifies_two_schema_failures_as_model_output() -> None:
    """连续两份坏结构应归类为模型输出故障，而不是 TURN_CONTRACT_INVALID。"""

    client = SequencedTurnDecisionClient([{"kind": "single_action"}, {"kind": "single_action"}])
    context = cast(HostAgentContext, SimpleNamespace(to_json_dict=lambda: {}))

    with pytest.raises(TurnExecutionError) as caught:
        await PromptHostTurnDecisionModel(client).generate(context)

    assert caught.value.code == "MODEL_OUTPUT_UNREADABLE"
    assert caught.value.retryable is True
    assert client.calls == 2


class SemanticPlanClient:
    def __init__(self, results: list[dict]) -> None:
        self.results = results
        self.calls = 0

    async def generate(self, *, schema_name, schema, instructions, input_payload):
        assert schema_name == "trpg_turn_plan"
        assert schema["title"] == "ActionPlan"
        assert "SingleActionDecision" not in json.dumps(schema)
        assert "ActionAdjudication" not in instructions
        assert "keeper_capabilities" not in input_payload
        result = self.results[self.calls]
        self.calls += 1
        return result


async def test_semantic_turn_planner_returns_action_plan_only() -> None:
    client = SemanticPlanClient(
        [
            {
                "kind": "action_plan",
                "goal": "观察房间",
                "steps": [{"kind": "action", "semantic_goal": "观察房间"}],
            }
        ]
    )
    context = cast(
        TurnPlanningContext,
        SimpleNamespace(
            player_input=SimpleNamespace(client_action_id="semantic-1"),
            to_json_dict=lambda: {"player_input": {"utterance": "观察房间"}},
        ),
    )

    plan = await PromptTurnPlanner(client).generate(context)

    assert isinstance(plan, ActionPlan)
    assert len(plan.steps) == 1


async def test_semantic_turn_planner_retries_bad_structure_once() -> None:
    client = SemanticPlanClient(
        [
            {"kind": "single_action"},
            {
                "kind": "action_plan",
                "goal": "先观察再询问",
                "steps": [
                    {"kind": "action", "semantic_goal": "观察"},
                    {"kind": "dialogue", "semantic_goal": "询问"},
                ],
            },
        ]
    )
    context = cast(
        TurnPlanningContext,
        SimpleNamespace(
            player_input=SimpleNamespace(client_action_id="semantic-2"),
            to_json_dict=lambda: {"player_input": {"utterance": "先观察再询问"}},
        ),
    )

    plan = await PromptTurnPlanner(client).generate(context)

    assert len(plan.steps) == 2
    assert client.calls == 2


async def test_semantic_turn_planner_classifies_transient_provider_failure() -> None:
    failure = httpx.ReadTimeout(
        "timeout",
        request=httpx.Request("POST", "https://example.test/chat/completions"),
    )

    class FailingClient:
        async def generate(self, **kwargs):
            del kwargs
            raise failure

    context = cast(
        TurnPlanningContext,
        SimpleNamespace(
            player_input=SimpleNamespace(client_action_id="semantic-timeout"),
            to_json_dict=lambda: {"player_input": {"utterance": "观察房间"}},
        ),
    )

    with pytest.raises(TurnExecutionError) as caught:
        await PromptTurnPlanner(FailingClient()).generate(context)

    assert caught.value.code == "MODEL_UPSTREAM_UNAVAILABLE"
    assert caught.value.retryable is True
    assert caught.value.__cause__ is failure


async def test_responses_client_posts_strict_schema_and_parses_output() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": '{"kind":"unknown"}',
                            }
                        ],
                    }
                ]
            },
        )

    client = OpenAIResponsesJsonClient(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )

    result = await client.generate(
        schema_name="test_schema",
        schema={"type": "object"},
        instructions="Return JSON.",
        input_payload={"safe": True},
    )

    assert result == {"kind": "unknown"}
    assert captured["store"] is False
    assert captured["text"]["format"]["type"] == "json_schema"
    assert captured["text"]["format"]["strict"] is True


async def test_qwen_client_posts_json_mode_with_schema_in_instructions() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"kind":"unknown"}',
                        }
                    }
                ]
            },
        )

    client = QwenChatCompletionsJsonClient(
        api_key="test-key",
        base_url="https://dashscope.example/compatible-mode/v1/",
        model="qwen3.7-plus",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    schema = {
        "type": "object",
        "properties": {"kind": {"type": "string"}},
        "required": ["kind"],
        "additionalProperties": False,
    }

    result = await client.generate(
        schema_name="test_schema",
        schema=schema,
        instructions="Return the structured result.",
        input_payload={"safe": True},
    )

    body = captured["body"]
    assert result == {"kind": "unknown"}
    assert captured["url"].endswith("/compatible-mode/v1/chat/completions")
    assert captured["authorization"] == "Bearer test-key"
    assert body["model"] == "qwen3.7-plus"
    assert body["response_format"] == {"type": "json_object"}
    assert body["enable_thinking"] is False
    assert "test_schema" in body["messages"][0]["content"]
    assert '"additionalProperties":false' in body["messages"][0]["content"]
    assert json.loads(body["messages"][1]["content"]) == {"safe": True}


async def test_deepseek_client_posts_compatible_json_mode_without_qwen_fields() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": '{"kind":"unknown"}',
                        }
                    }
                ]
            },
        )

    client = DeepSeekChatCompletionsJsonClient(
        api_key="test-key",
        base_url="https://api.deepseek.example/v1/",
        model="deepseek-chat",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
    )
    result = await client.generate(
        schema_name="test_schema",
        schema={"type": "object"},
        instructions="返回结构化结果。",
        input_payload={"safe": True},
    )

    body = captured["body"]
    assert result == {"kind": "unknown"}
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["authorization"] == "Bearer test-key"
    assert body["model"] == "deepseek-chat"
    assert body["response_format"] == {"type": "json_object"}
    # DeepSeek 的 `thinking` 默认是 enabled（reasoning_effort 默认 high），不显式
    # 关掉就会在每次结构化输出前白烧一段推理——实测 qnaigc 端点上同一个 trivial
    # 请求 151 vs 5 个 completion tokens（issue #330）。我们只要那个 JSON 对象。
    assert body["thinking"] == {"type": "disabled"}
    # `enable_thinking` 是 Qwen 的字段名，别混进 DeepSeek 的请求体。
    assert "enable_thinking" not in body
    assert "test_schema" in body["messages"][0]["content"]
    assert "只返回一个 JSON 对象" in body["messages"][0]["content"]


def test_openai_provider_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings.model_validate(
            {
                "host_model_provider": "openai",
                "openai_api_key": None,
            }
        )


def test_qwen_provider_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="QWEN_API_KEY"):
        Settings.model_validate(
            {
                "host_model_provider": "qwen",
                "qwen_api_key": None,
            }
        )


def test_deepseek_provider_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="DEEPSEEK_API_KEY"):
        Settings.model_validate(
            {
                "host_model_provider": "deepseek",
                "deepseek_api_key": None,
            }
        )


def test_intent_schema_remains_strict_for_prompt_adapter() -> None:
    schema = Intent.model_json_schema(mode="serialization")
    assert schema["additionalProperties"] is False


def test_action_adjudication_schema_remains_strict_for_prompt_adapter() -> None:
    """Internal persistence serialization must not erase the provider schema."""

    schema = ActionAdjudication.model_json_schema(mode="serialization")

    assert schema["additionalProperties"] is False
    assert {
        "request_id",
        "source_revision",
        "actor_id",
        "summary",
        "target",
        "method",
        "persistence_intent",
        "check",
        "success_effects",
        "failure_effects",
    } <= schema["properties"].keys()
    assert "persistence_intent_explicit_marker" not in schema["properties"]


def _json_object_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"choices": [{"message": {"role": "assistant", "content": '{"kind":"unknown"}'}}]},
    )


def _fast_retry() -> ModelClientRetryPolicy:
    """退避缩到几乎为零，让重试测试不真的睡 0.5 秒。"""

    return ModelClientRetryPolicy(max_attempts=2, backoff_seconds=0.001)


def _deepseek_client(
    handler,
    *,
    retry_policy: ModelClientRetryPolicy | None = None,
) -> DeepSeekChatCompletionsJsonClient:
    return DeepSeekChatCompletionsJsonClient(
        api_key="test-key",
        base_url="https://api.deepseek.example/v1",
        model="deepseek-chat",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
        retry_policy=retry_policy or _fast_retry(),
    )


async def _generate(client) -> dict:
    return await client.generate(
        schema_name="test_schema",
        schema={"type": "object"},
        instructions="返回结构化结果。",
        input_payload={"safe": True},
    )


class _ScriptedStepClient:
    """为步骤适配器注入成功结果或指定异常，不经过真实 HTTP。"""

    def __init__(self, result: dict | BaseException) -> None:
        self._result = result
        self.input_payload: dict | None = None

    async def generate(
        self,
        *,
        schema_name: str,
        schema: dict,
        instructions: str,
        input_payload: dict,
    ) -> dict:
        assert schema_name == "trpg_action_plan_step_adjudication"
        assert schema
        assert instructions
        assert input_payload["plan_id"] == "plan-step-error"
        self.input_payload = input_payload
        if isinstance(self._result, BaseException):
            raise self._result
        return self._result


def _step_error_context() -> ActionPlanStepContext:
    player_input = PlayerInput(
        room_id="room-step-error",
        player_id="player-step-error",
        actor_id="actor-step-error",
        client_action_id="action-step-error",
        utterance="检查当前房间",
    )
    return ActionPlanStepContext(
        player_input=player_input,
        plan_id="plan-step-error",
        plan_goal="检查房间后继续调查",
        step_index=0,
        step_request_id="action-step-error-step-0",
        step=ActionPlanStep(kind="action", semantic_goal="检查当前房间"),
        player_view=PlayerView(
            room_id=player_input.room_id,
            player_id=player_input.player_id,
            actor_id=player_input.actor_id,
            background="测试场景",
            scene_id="scene-step-error",
            phase="playing",
            revision="1",
            self_actor=SelfActorView(id=player_input.actor_id, name="调查员"),
            scene=SceneView(
                id="scene-step-error",
                name="测试房间",
                description="一间用于测试的房间。",
            ),
        ),
    )


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ReadTimeout(
            "timeout",
            request=httpx.Request("POST", "https://example.test/chat/completions"),
        ),
        httpx.ConnectError(
            "reset",
            request=httpx.Request("POST", "https://example.test/chat/completions"),
        ),
        httpx.HTTPStatusError(
            "rate limited",
            request=httpx.Request("POST", "https://example.test/chat/completions"),
            response=httpx.Response(
                429,
                request=httpx.Request("POST", "https://example.test/chat/completions"),
            ),
        ),
        httpx.HTTPStatusError(
            "server error",
            request=httpx.Request("POST", "https://example.test/chat/completions"),
            response=httpx.Response(
                503,
                request=httpx.Request("POST", "https://example.test/chat/completions"),
            ),
        ),
    ],
)
async def test_step_adjudicator_classifies_transient_provider_failure(
    failure: Exception,
) -> None:
    adjudicator = PromptActionPlanStepAdjudicator(_ScriptedStepClient(failure))

    with pytest.raises(TurnExecutionError) as caught:
        await adjudicator.adjudicate(_step_error_context())

    assert caught.value.code == "MODEL_UPSTREAM_UNAVAILABLE"
    assert caught.value.retryable is True
    assert caught.value.__cause__ is failure


async def test_step_adjudicator_classifies_unreadable_and_invalid_output() -> None:
    unreadable = StructuredOutputError("DeepSeek message has no text content")
    adjudicator = PromptActionPlanStepAdjudicator(_ScriptedStepClient(unreadable))

    with pytest.raises(TurnExecutionError) as caught:
        await adjudicator.adjudicate(_step_error_context())
    assert caught.value.code == "MODEL_OUTPUT_UNREADABLE"
    assert caught.value.__cause__ is unreadable

    invalid = PromptActionPlanStepAdjudicator(_ScriptedStepClient({}))
    with pytest.raises(TurnExecutionError) as caught:
        await invalid.adjudicate(_step_error_context())
    assert caught.value.code == "MODEL_OUTPUT_UNREADABLE"
    assert isinstance(caught.value.__cause__, ValidationError)


async def test_step_adjudicator_receives_published_narration_as_soft_context() -> None:
    context = _step_error_context()
    history = RecentTurnContext(
        room_id=context.player_input.room_id,
        viewer_player_id=context.player_input.player_id,
        as_of_revision=context.player_view.revision,
        turns=(
            RecentTurn(
                correlation_id="previous-action",
                source_player_id=context.player_input.player_id,
                source_actor_id=context.player_input.actor_id,
                scene_id=context.player_view.scene.id,
                player_utterance=VisibleHistoryText(
                    text="查看房间",
                    visibility="player_scoped",
                ),
                published_narration=VisibleHistoryText(
                    text="桌上散放着几册普通读物。",
                    visibility="player_scoped",
                ),
            ),
        ),
    )
    client = _ScriptedStepClient(
        {
            "request_id": context.step_request_id,
            "source_revision": context.player_view.revision,
            "actor_id": context.player_input.actor_id,
            "summary": context.step.semantic_goal,
            "target": {"kind": "location", "id": context.player_view.scene.id},
            "method": {"family": "action", "description": context.step.semantic_goal},
            "persistence_intent": "none",
            "check": {"mode": "none"},
            "success_effects": [{"type": "narrative_only"}],
            "failure_effects": [],
        }
    )

    await PromptActionPlanStepAdjudicator(client).adjudicate(
        context.model_copy(update={"recent_history": history})
    )

    assert client.input_payload is not None
    assert (
        client.input_payload["recent_history"]["turns"][0]["published_narration"]["text"]
        == "桌上散放着几册普通读物。"
    )


async def test_step_adjudicator_leaves_unknown_failure_for_orchestrator_fallback() -> None:
    unknown = RuntimeError("unexpected adapter bug")
    adjudicator = PromptActionPlanStepAdjudicator(_ScriptedStepClient(unknown))

    with pytest.raises(RuntimeError) as caught:
        await adjudicator.adjudicate(_step_error_context())

    assert caught.value is unknown


async def test_structured_client_retries_after_timeout_and_succeeds() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ReadTimeout("upstream timed out", request=request)
        return _json_object_response()

    result = await _generate(_deepseek_client(handler))

    assert result == {"kind": "unknown"}
    assert attempts["count"] == 2


async def test_structured_client_logs_allowlisted_trace_usage_and_attempts() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ReadTimeout("upstream timed out", request=request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": '{"kind":"unknown"}'}}],
                "usage": {
                    "prompt_tokens": 13,
                    "completion_tokens": 5,
                    "total_tokens": 18,
                },
            },
        )

    with capture_logs() as logs:
        result = await _deepseek_client(handler).generate(
            schema_name="trpg_turn_plan",
            schema={"type": "object"},
            instructions="secret-prompt-must-not-appear",
            input_payload={
                "player_input": {
                    "client_action_id": "action-1234567890-secret-tail",
                    "utterance": "secret-utterance-must-not-appear",
                },
                "keeper_capabilities": {"secret": "keeper-payload-must-not-appear"},
            },
        )

    assert result == {"kind": "unknown"}
    completed = next(item for item in logs if item["event"] == "structured_model_call_completed")
    assert completed["action"] == "action-12345"
    assert completed["stage"] == "trpg_turn_plan"
    assert completed["provider"] == "deepseek"
    assert completed["model"] == "deepseek-chat"
    assert completed["transport_attempts"] == 2
    assert completed["prompt_tokens"] == 13
    assert completed["completion_tokens"] == 5
    assert completed["total_tokens"] == 18
    assert isinstance(completed["duration_ms"], int)
    rendered = json.dumps(logs, ensure_ascii=False)
    assert "secret-prompt-must-not-appear" not in rendered
    assert "secret-utterance-must-not-appear" not in rendered
    assert "keeper-payload-must-not-appear" not in rendered
    assert "secret-tail" not in rendered


async def test_structured_client_retries_after_server_error_and_succeeds() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(503, json={"error": "upstream unavailable"})
        return _json_object_response()

    result = await _generate(_deepseek_client(handler))

    assert result == {"kind": "unknown"}
    assert attempts["count"] == 2


async def test_structured_client_reraises_original_error_after_retries_exhausted() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ReadTimeout("upstream timed out", request=request)

    with capture_logs() as logs, pytest.raises(httpx.ReadTimeout):
        await _generate(_deepseek_client(handler))

    assert attempts["count"] == 2
    failed = next(item for item in logs if item["event"] == "structured_model_call_failed")
    assert failed["failure_code"] == "transport_exhausted"
    assert failed["transport_attempts"] == 2
    assert failed["provider"] == "deepseek"


async def test_structured_client_does_not_retry_client_errors() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        return httpx.Response(400, json={"error": "bad request"})

    with pytest.raises(httpx.HTTPStatusError):
        await _generate(_deepseek_client(handler))

    assert attempts["count"] == 1


async def test_structured_client_retries_rate_limit_responses() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            return httpx.Response(429, json={"error": "rate limited"})
        return _json_object_response()

    result = await _generate(_deepseek_client(handler))

    assert result == {"kind": "unknown"}
    assert attempts["count"] == 2


async def test_structured_client_attempt_count_follows_the_policy() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        raise httpx.ConnectError("connection reset", request=request)

    policy = ModelClientRetryPolicy(max_attempts=4, backoff_seconds=0.001)
    with pytest.raises(httpx.ConnectError):
        await _generate(_deepseek_client(handler, retry_policy=policy))

    assert attempts["count"] == 4


async def test_qwen_client_retries_transient_failures() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ReadTimeout("upstream timed out", request=request)
        return _json_object_response()

    client = QwenChatCompletionsJsonClient(
        api_key="test-key",
        base_url="https://dashscope.example/compatible-mode/v1",
        model="qwen3.7-plus",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
        retry_policy=_fast_retry(),
    )

    assert await _generate(client) == {"kind": "unknown"}
    assert attempts["count"] == 2


async def test_openai_client_retries_transient_failures() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ReadTimeout("upstream timed out", request=request)
        return httpx.Response(
            200,
            json={
                "output": [
                    {
                        "type": "message",
                        "content": [{"type": "output_text", "text": '{"kind":"unknown"}'}],
                    }
                ]
            },
        )

    client = OpenAIResponsesJsonClient(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
        retry_policy=_fast_retry(),
    )

    assert await _generate(client) == {"kind": "unknown"}
    assert attempts["count"] == 2


def test_retry_policy_backoff_is_exponential() -> None:
    policy = ModelClientRetryPolicy(max_attempts=4, backoff_seconds=0.5)
    assert [policy.delay_before(attempt) for attempt in (1, 2, 3)] == [0.5, 1.0, 2.0]


def test_transient_classification_covers_transport_and_server_errors() -> None:
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    assert is_transient_model_error(httpx.ReadTimeout("timeout", request=request))
    assert is_transient_model_error(httpx.ConnectError("reset", request=request))
    for status in (500, 502, 503, 429):
        error = httpx.HTTPStatusError(
            "server error",
            request=request,
            response=httpx.Response(status, request=request),
        )
        assert is_transient_model_error(error)
    for status in (400, 401, 403, 404, 422):
        error = httpx.HTTPStatusError(
            "client error",
            request=request,
            response=httpx.Response(status, request=request),
        )
        assert not is_transient_model_error(error)
    assert not is_transient_model_error(ValueError("malformed structured output"))


def _retry_policy_of(owner: object) -> ModelClientRetryPolicy:
    """穿过 composer / planner，取它实际持有的 client 的重试策略。

    这些持有者的声明类型都是 Protocol，直接点私有属性过不了 ty。
    """

    return getattr(getattr(owner, "_client"), "_retry_policy")  # noqa: B009


def test_configured_retry_policy_reaches_every_structured_client() -> None:
    """每个 StructuredJsonClient 构造点都必须走 `model_client_retry_policy`。

    否则那个 client 会静默吃默认值、无视 `MODEL_CLIENT_*`，运维就没法为它
    调整或关闭重试——一键建卡背景与立绘提示词曾经就是这样漏掉的。
    """

    settings = Settings.model_validate(
        {
            "host_model_provider": "deepseek",
            "deepseek_api_key": "test-key",
            "character_background_provider": "deepseek",
            "portrait_prompt_provider": "deepseek",
            "model_client_max_attempts": 4,
            "model_client_retry_backoff_seconds": 1.5,
        }
    )
    expected = ModelClientRetryPolicy(max_attempts=4, backoff_seconds=1.5)
    assert model_client_retry_policy(settings) == expected

    background_service = build_character_background_service(settings)
    assert _retry_policy_of(background_service._composer) == expected

    portrait_service = build_portrait_generation_service(settings)
    assert _retry_policy_of(portrait_service._prompt_composer) == expected

    engine_store = InMemoryEngineStore()
    plan_application = build_action_plan_turn_application(
        store=engine_store,
        engine=RuleEngineService(engine_store),
        adjudication_engine=AdjudicationEngineService(engine_store),
        settings=settings,
    )
    assert _retry_policy_of(plan_application._planner) == expected


def test_opening_narration_client_does_not_retry() -> None:
    """开场路径显式不重试。

    开场整段被 `anyio.fail_after(opening_narration_timeout_seconds)` 包住，那是
    总预算；单次请求预算是 `deepseek_timeout_seconds`。两者默认都是 30 秒，第一次
    请求耗尽预算时外层 deadline 同时到期，退避与第二次尝试会被取消。与其配一个
    永远不生效的策略，不如如实地不重试——开场有确定性模板兜底。
    """

    settings = Settings.model_validate(
        {
            "host_model_provider": "deepseek",
            "deepseek_api_key": "test-key",
            "model_client_max_attempts": 4,
        }
    )
    model, _ = _configured_opening_models(settings)
    assert _retry_policy_of(model).max_attempts == 1


async def test_outer_deadline_equal_to_request_timeout_cancels_the_retry() -> None:
    """坐实上面那条注释：外层预算等于单次预算时，重试根本不会发生。

    每次尝试都耗满单次预算才失败，所以第一次尝试就把总预算用光了。
    """

    per_request = 0.2
    attempts = {"count": 0}

    async def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        await anyio.sleep(per_request)
        raise httpx.ReadTimeout("upstream timed out", request=request)

    client = DeepSeekChatCompletionsJsonClient(
        api_key="test-key",
        base_url="https://api.deepseek.example/v1",
        model="deepseek-chat",
        timeout_seconds=per_request,
        transport=httpx.MockTransport(handler),
        retry_policy=ModelClientRetryPolicy(max_attempts=2, backoff_seconds=0.05),
    )

    with pytest.raises(TimeoutError):
        with anyio.fail_after(per_request):
            await _generate(client)
    assert attempts["count"] == 1

    # 对照：总预算容得下两次尝试时，重试照常发生。
    attempts["count"] = 0
    with pytest.raises(httpx.ReadTimeout):
        with anyio.fail_after(per_request * 2 + 0.05 + 0.5):
            await _generate(client)
    assert attempts["count"] == 2


def _map(exc: Exception) -> tuple[str, str, bool]:
    from app.controller.ws import _map_turn_error

    return _map_turn_error(exc)


def test_planner_transport_failures_get_their_own_error_code() -> None:
    """规划阶段的模型故障不能再落进 `TURN_INTERNAL_ERROR` 兜底（#285）。

    兜底的语义是「我们没预料到这个失败」。一个 30 秒超时是完全预料得到的，
    把它和引擎内部错误混在一起，玩家既不知道能否重试，也让兜底本身失去意义。
    """

    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    transport_failures: list[Exception] = [
        httpx.ReadTimeout("timeout", request=request),
        httpx.ConnectError("reset", request=request),
        httpx.HTTPStatusError(
            "server error",
            request=request,
            response=httpx.Response(503, request=request),
        ),
        httpx.HTTPStatusError(
            "rate limited",
            request=request,
            response=httpx.Response(429, request=request),
        ),
    ]
    for exc in transport_failures:
        code, message, retryable = _map(exc)
        assert code == "MODEL_UPSTREAM_UNAVAILABLE", exc
        assert retryable is True
        # 这类失败发生在裁决提交规则引擎之前，没有任何权威效果落库。
        assert "未生效" in message
        assert "已保存" not in message


def test_unreadable_model_output_gets_its_own_error_code() -> None:
    """上游回了 200 但正文读不懂，与「没拿到回复」是两回事。"""

    code, message, retryable = _map(StructuredOutputError("not valid JSON"))
    assert code == "MODEL_OUTPUT_UNREADABLE"
    assert retryable is True
    assert "未生效" in message
    assert "已保存" not in message


def test_client_errors_still_fall_through_to_contract_or_fallback() -> None:
    """4xx 不属于上游不可用，分类不能把它一起认领走。"""

    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    code, _, _ = _map(
        httpx.HTTPStatusError(
            "bad request",
            request=request,
            response=httpx.Response(400, request=request),
        )
    )
    assert code == "TURN_INTERNAL_ERROR"


async def test_client_raises_structured_output_error_on_unparsable_body() -> None:
    """上游 200 + 非 JSON 正文：客户端抛可分类的异常，而不是裸 ValueError。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "抱歉，我不能这样做。"}}]
            },
        )

    with capture_logs() as logs, pytest.raises(StructuredOutputError):
        await _generate(_deepseek_client(handler))

    failed = next(item for item in logs if item["event"] == "structured_model_call_failed")
    assert failed["failure_code"] == "structured_output_unreadable"
    assert failed["transport_attempts"] == 1
    assert not any(item["event"] == "structured_model_call_completed" for item in logs)


async def test_client_raises_structured_output_error_when_json_is_not_an_object() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"role": "assistant", "content": "[1, 2, 3]"}}]},
        )

    with pytest.raises(StructuredOutputError):
        await _generate(_deepseek_client(handler))


class _RecordingLogger:
    """记下 structlog 调用的事件名与结构化字段。

    堆栈是作为 `stack=` 字段传出去的，不在 caplog 的渲染文本里，直接捕获调用
    参数才能断言它的内容。
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    def warning(self, event: str, **kwargs: object) -> None:
        self.calls.append(("warning", event, dict(kwargs)))

    def error(self, event: str, **kwargs: object) -> None:
        self.calls.append(("error", event, dict(kwargs)))


def _log_failure_with(code: str, monkeypatch: pytest.MonkeyPatch) -> _RecordingLogger:
    from app.core import turn_observability

    recorder = _RecordingLogger()
    monkeypatch.setattr(turn_observability, "logger", recorder)
    try:
        raise RuntimeError("boom")
    except RuntimeError as exc:
        turn_observability.log_turn_failed(
            room_id="room-1",
            correlation_id="action-1",
            stage="行动计划",
            code=code,
            error_type=type(exc).__name__,
            exc=exc,
        )
    return recorder


def test_unclassified_failure_logs_a_stack_trace_to_the_server_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """兜底必须留下可定位的证据，否则事后只有一个错误码可查（#285）。

    #285 的原始正文正是在拿不到堆栈的情况下靠读代码猜出来的，猜错了机制。
    """

    recorder = _log_failure_with("TURN_INTERNAL_ERROR", monkeypatch)
    errors = [call for call in recorder.calls if call[0] == "error"]
    assert len(errors) == 1
    _, event, fields = errors[0]
    assert event == "turn_unclassified_exception"
    assert "Traceback" in fields["stack"]
    assert "RuntimeError: boom" in fields["stack"]
    # 定位号与阶段必须一并记下，否则玩家报来的定位号仍然查不到东西。
    assert fields["action"] == "action-1"
    assert fields["stage"] == "行动计划"


def test_classified_failure_does_not_log_a_stack_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已分类的失败是预期内的，不该往日志里灌堆栈。"""

    recorder = _log_failure_with("MODEL_UPSTREAM_UNAVAILABLE", monkeypatch)
    assert [call for call in recorder.calls if call[0] == "error"] == []
    assert [call for call in recorder.calls if call[0] == "warning"]


async def test_step_failure_log_contains_correlation_and_unclassified_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """步骤定位日志须足够排障，但不能携带模型输入或玩家不可见上下文。"""

    from app.core import action_plan_turn

    recorder = _RecordingLogger()
    monkeypatch.setattr(action_plan_turn, "logger", recorder)
    try:
        raise RuntimeError("unexpected adjudicator bug")
    except RuntimeError as error:
        failure = ActionPlanStepFailure(
            correlation_id="b97b36bc-full-correlation",
            plan_id="plan-298",
            step_id="step-2",
            step_index=1,
            attempt=2,
            duration_ms=60001,
            code="STEP_ADJUDICATOR_FAILED",
            error=error,
            completed_steps=1,
        )

    await action_plan_turn._log_step_adjudication_failure(failure)

    assert len(recorder.calls) == 1
    level, event, fields = recorder.calls[0]
    assert level == "error"
    assert event == "action_plan_step_adjudication_unclassified"
    assert fields["action"] == failure.correlation_id
    assert fields["stage"] == "步骤裁决"
    assert fields["plan"] == failure.plan_id
    assert fields["step"] == failure.step_id
    assert fields["step_index"] == 1
    assert fields["attempt"] == 2
    assert fields["duration_ms"] == 60001
    assert fields["completed_steps"] == 1
    assert fields["authoritative_submitted"] is False
    assert "Traceback" in fields["stack"]
    assert "RuntimeError: unexpected adjudicator bug" in fields["stack"]
    assert "prompt" not in fields
    assert "response" not in fields


async def test_classified_step_failure_logs_warning_without_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core import action_plan_turn

    recorder = _RecordingLogger()
    monkeypatch.setattr(action_plan_turn, "logger", recorder)
    failure = ActionPlanStepFailure(
        correlation_id="action-298",
        plan_id="plan-298",
        step_id="step-2",
        step_index=1,
        attempt=1,
        duration_ms=30,
        code="MODEL_UPSTREAM_UNAVAILABLE",
        error=httpx.ReadTimeout("timeout"),
        completed_steps=1,
    )

    await action_plan_turn._log_step_adjudication_failure(failure)

    assert len(recorder.calls) == 1
    level, event, fields = recorder.calls[0]
    assert level == "warning"
    assert event == "action_plan_step_adjudication_failed"
    assert fields["code"] == "MODEL_UPSTREAM_UNAVAILABLE"
    assert fields["error_type"] == "ReadTimeout"
    assert "stack" not in fields


async def test_non_json_http_body_is_classified_as_unreadable_output() -> None:
    """上游 200 但响应体根本不是 JSON（代理的 HTML 错误页是典型）。

    解码分两层：HTTP 响应体 → JSON，再 JSON 里的 content → JSON 对象。
    只包住第二层的话，第一层失败仍然会掉进 `TURN_INTERNAL_ERROR` 兜底。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>502 Bad Gateway</body></html>")

    with pytest.raises(StructuredOutputError):
        await _generate(_deepseek_client(handler))


async def test_qwen_non_json_http_body_is_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="upstream proxy error")

    client = QwenChatCompletionsJsonClient(
        api_key="test-key",
        base_url="https://dashscope.example/compatible-mode/v1",
        model="qwen3.7-plus",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
        retry_policy=_fast_retry(),
    )
    with pytest.raises(StructuredOutputError):
        await _generate(client)


async def test_openai_non_json_http_body_is_classified() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="upstream proxy error")

    client = OpenAIResponsesJsonClient(
        api_key="test-key",
        base_url="https://example.test/v1",
        model="test-model",
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
        retry_policy=_fast_retry(),
    )
    with pytest.raises(StructuredOutputError):
        await _generate(client)
