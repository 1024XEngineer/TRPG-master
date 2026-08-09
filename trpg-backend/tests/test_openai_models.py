from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from collaboration_framework.contracts import (
    ActionPlan,
    ActionResult,
    DefaultCheck,
    Intent,
    MatchedTarget,
    ModuleContent,
    PlayerInput,
    PlayerView,
    RuleCheckResult,
    SceneView,
    SelfActorView,
    SingleActionDecision,
    VisibleEntity,
    VisibleFact,
)
from collaboration_framework.engine import (
    ActorResources,
    ActorState,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
)
from collaboration_framework.host.application import PlayerViewProjector
from collaboration_framework.host.schemas import (
    HostAgentContext,
    IntentContext,
    NarrationContext,
    RecentTurnContext,
)
from pydantic import ValidationError

from app.adapters.deepseek_models import DeepSeekChatCompletionsJsonClient
from app.adapters.openai_models import (
    _ACTION_PLAN_NARRATION_INSTRUCTIONS,
    OpenAIResponsesJsonClient,
    PromptHostTurnDecisionModel,
    PromptIntentModel,
    PromptNarrationModel,
)
from app.adapters.qwen_models import QwenChatCompletionsJsonClient
from app.core.config import Settings

ROOT = Path(__file__).resolve().parents[2]


def test_action_plan_narration_uses_final_post_roll_outcome() -> None:
    """叙事不能把消耗幸运或强推之前的失败当成最终结果。"""

    assert "消耗幸运" in _ACTION_PLAN_NARRATION_INSTRUCTIONS
    assert "outcome=success" in _ACTION_PLAN_NARRATION_INSTRUCTIONS
    assert "最终权威结果" in _ACTION_PLAN_NARRATION_INSTRUCTIONS


def load_paper_chase() -> ModuleContent:
    examples = (
        ROOT
        / "agent-collaboration-framework"
        / "docs"
        / "module-parser"
        / "examples"
        / "module-content-validation"
    )
    for path in examples.rglob("module-content-draft.json"):
        payload = path.read_text(encoding="utf-8")
        if '"module_id": "paper-chase-zh-coc7"' in payload:
            return ModuleContent.model_validate_json(payload)
    raise AssertionError("Paper Chase ModuleContent fixture was not found")


def conversation_state(module: ModuleContent) -> GameState:
    entities = {entity.id: dict(entity.state) for entity in module.entities}
    entities["cemetery_figure"]["willing_to_talk"] = True
    return GameState(
        room_id="room_llm",
        scene_id="conversation",
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


class ScriptedStructuredClient:
    def __init__(self) -> None:
        self.backgrounds: list[str] = []

    async def generate(
        self,
        *,
        schema_name: str,
        schema: dict,
        instructions: str,
        input_payload: dict,
    ) -> dict:
        assert schema
        assert instructions
        if schema_name == "trpg_intent":
            utterance = input_payload["player_input"]["utterance"]
            if "离开" in utterance:
                verb = "let_leave"
                checkpoint_id = "let_douglas_leave"
            else:
                verb = "talk"
                checkpoint_id = "talk_to_figure"
            return {
                "kind": "action",
                "verb": verb,
                "target": {"matched": True, "id": "cemetery_figure"},
                "check": {
                    "route": "module",
                    "checkpoint_id": checkpoint_id,
                    "proposed_skills": [],
                },
                "approach": utterance,
                "summary": utterance,
            }
        self.backgrounds.append(input_payload["background"])
        visible = input_payload["action_result"]["visible_facts"]
        return {
            "kind": "narration",
            "text": " ".join(fact["text"] for fact in visible) or "行动完成。",
            "claimed_fact_ids": [fact["id"] for fact in visible],
            "suggested_actions": [],
        }


class ImmersionPromptCaptureClient:
    def __init__(self) -> None:
        self.instructions: dict[str, str] = {}
        self.inputs: dict[str, dict] = {}

    async def generate(
        self,
        *,
        schema_name: str,
        schema: dict,
        instructions: str,
        input_payload: dict,
    ) -> dict:
        assert schema
        self.instructions[schema_name] = instructions
        self.inputs[schema_name] = input_payload
        if schema_name == "trpg_intent":
            return {
                "kind": "unknown",
                "verb": "orient",
                "target": {"matched": False, "raw": "我在哪里"},
                "check": {"route": "none"},
                "approach": None,
                "declarations": [],
                "initiated_by_target": False,
                "summary": "询问当前处境",
                "clarification_question": "请描述我此刻所处的环境。",
            }
        return {
            "kind": "narration",
            "text": "托马斯·金博尔就在你面前，安静地等着你的答复。",
            "claimed_fact_ids": [],
            "suggested_actions": [],
        }


class EquivalentVerbClient:
    def __init__(self) -> None:
        self.verbs = iter(("观察", "observe"))

    async def generate(
        self,
        *,
        schema_name: str,
        schema: dict,
        instructions: str,
        input_payload: dict,
    ) -> dict:
        assert schema_name == "trpg_intent"
        assert schema
        assert instructions
        assert (
            input_payload["player_view"]["scene"]["visible_entities"][0]["id"] == "cemetery_figure"
        )
        return {
            "kind": "action",
            "verb": next(self.verbs),
            "target": {"matched": True, "id": "cemetery_figure"},
            "check": {"route": "none"},
            "approach": None,
            "summary": "观察道格拉斯",
        }


class ChineseTravelVerbClient:
    async def generate(
        self,
        *,
        schema_name: str,
        schema: dict,
        instructions: str,
        input_payload: dict,
    ) -> dict:
        assert schema_name == "trpg_intent"
        assert schema
        assert instructions
        assert any(
            item["id"] == "library"
            for item in input_payload["player_view"]["scene"]["available_exits"]
        )
        return {
            "kind": "action",
            "verb": "前往",
            "target": {"matched": True, "id": "library"},
            "check": {"route": "none"},
            "approach": None,
            "summary": "前往图书馆",
        }


async def test_prompt_intent_keeps_distinct_module_actions_canonical() -> None:
    player_input = PlayerInput(
        room_id="room_prompt",
        player_id="player_1",
        actor_id="actor_1",
        client_action_id="look-douglas",
        utterance="我看看道格拉斯",
    )
    player_view = PlayerView(
        room_id="room_prompt",
        player_id="player_1",
        actor_id="actor_1",
        background="玩家可见的测试背景。",
        scene_id="conversation",
        phase="playing",
        revision="0",
        self_actor=SelfActorView(id="actor_1", name="调查员"),
        scene=SceneView(
            id="conversation",
            name="墓碑旁",
            description="道格拉斯停在墓碑旁。",
            visible_entities=(
                VisibleEntity(
                    id="cemetery_figure",
                    kind="npc",
                    name="道格拉斯·金博尔",
                    aliases=("道格拉斯",),
                    description="一位爱书人。",
                ),
            ),
        ),
    )
    model = PromptIntentModel(EquivalentVerbClient())
    context = IntentContext(
        player_input=player_input,
        player_view=player_view,
        recent_history=RecentTurnContext.empty(
            player_input=player_input,
            player_view=player_view,
        ),
    )

    first = Intent.model_validate(await model.generate(context))
    second = Intent.model_validate(await model.generate(context))

    assert first.verb == second.verb == "observe"


async def test_prompts_treat_scene_orientation_as_narration_not_form_validation() -> None:
    player_input = PlayerInput(
        room_id="room_prompt",
        player_id="player_1",
        actor_id="actor_1",
        client_action_id="where-am-i",
        utterance="我在哪里",
    )
    player_view = PlayerView(
        room_id="room_prompt",
        player_id="player_1",
        actor_id="actor_1",
        background="玩家可见的测试背景。",
        scene_id="client_briefing",
        phase="playing",
        revision="0",
        self_actor=SelfActorView(
            id="actor_1",
            name="调查员",
            occupation="私家侦探",
        ),
        scene=SceneView(
            id="client_briefing",
            name="托马斯的会客室",
            description="托马斯坐在你面前，等待你回应他的委托。",
            visible_entities=(
                VisibleEntity(
                    id="thomas",
                    kind="npc",
                    name="托马斯·金博尔",
                    aliases=("托马斯",),
                    description="委托调查员寻找五本失窃藏书。",
                ),
            ),
        ),
    )
    client = ImmersionPromptCaptureClient()
    intent_payload = await PromptIntentModel(client).generate(
        IntentContext(
            player_input=player_input,
            player_view=player_view,
            recent_history=RecentTurnContext.empty(
                player_input=player_input,
                player_view=player_view,
            ),
        )
    )
    intent = Intent.model_validate(intent_payload)
    narration = await PromptNarrationModel(client).generate(
        NarrationContext(
            background="禁酒令时期的密歇根州；叙事安静、克制。",
            player_input=player_input,
            intent=intent,
            action_result=ActionResult(
                request_id="where-am-i",
                action_id="action:where-am-i",
                resolution="unrecognized",
                outcome="not_applicable",
                visible_facts=(
                    VisibleFact(
                        id="action:where-am-i:unrecognized:result:1",
                        text="没有找到与该说法对应的当前场景目标。",
                    ),
                ),
                narration_constraints=("不得编造目标或状态变化。",),
                view_revision="0",
            ),
            player_view=player_view,
            recent_history=RecentTurnContext.empty(
                player_input=player_input,
                player_view=player_view,
            ),
        )
    )

    intent_instructions = client.instructions["trpg_intent"]
    narration_instructions = client.instructions["trpg_narration"]
    assert "属于场景定位" in intent_instructions
    assert "感知请求" in intent_instructions
    assert "选择 default check" in intent_instructions
    assert "player_view.scene.id" in intent_instructions
    assert "只选择" in intent_instructions
    assert "最相关的一个 id" in intent_instructions
    assert "不要称它为元游戏问题" in intent_instructions
    assert "确认、感谢或承接语" in intent_instructions
    assert "kind=dialogue" in intent_instructions
    assert "当前连续场景期间的 published_narration" in intent_instructions
    assert "根据 PlayerView 直接给出" in narration_instructions
    assert "check_result 不为空" in narration_instructions
    assert "普通检定不能代替或补触发" in narration_instructions
    assert "一段场景描述" in narration_instructions
    assert "不要要求玩家先指定目标或先做检定" in narration_instructions
    assert "不得借此创造门窗、出口、人物、物品、路线" in narration_instructions
    assert "无动作的对话承接" in narration_instructions
    assert "不要追问" in narration_instructions
    assert "这项限制同样适用于角色对白" in narration_instructions
    assert "检定失败时尤其不得用对白补发新事实" in narration_instructions
    assert "text 只能包含玩家可见的角色内叙事" in narration_instructions
    assert "claimed_fact_ids" in narration_instructions
    assert "JSON/schema 片段" in narration_instructions
    assert "Markdown JSON 代码块" in narration_instructions
    serialized_view = client.inputs["trpg_narration"]["player_view"]
    assert serialized_view["scene"]["visible_entities"][0]["id"] == "thomas"
    assert serialized_view["scene"]["description"] == "托马斯坐在你面前，等待你回应他的委托。"
    assert serialized_view["self_actor"]["occupation"] == "私家侦探"
    assert narration["kind"] == "narration"
    assert narration["claimed_fact_ids"] == []


async def test_narration_receives_authoritative_default_check_result() -> None:
    player_input = PlayerInput(
        room_id="room_prompt",
        player_id="player_1",
        actor_id="actor_1",
        client_action_id="listen-carefully",
        utterance="我侧耳倾听周围的声音",
    )
    player_view = PlayerView(
        room_id="room_prompt",
        player_id="player_1",
        actor_id="actor_1",
        background="玩家可见的测试背景。",
        scene_id="quiet_room",
        phase="playing",
        revision="0",
        self_actor=SelfActorView(id="actor_1", name="调查员"),
        scene=SceneView(
            id="quiet_room",
            name="安静的房间",
            description="房间里只有钟表规律的滴答声。",
        ),
    )
    intent = Intent(
        kind="action",
        verb="listen",
        target=MatchedTarget(id="quiet_room"),
        check=DefaultCheck(proposed_skills=("listen",)),
        summary="侧耳倾听周围的声音",
    )
    action_result = ActionResult(
        request_id="listen-carefully",
        action_id="action:listen-carefully",
        resolution="direct",
        outcome="failure",
        check_result=RuleCheckResult(
            checkpoint_id=None,
            skill_id="listen",
            target_value=40,
            roll_value=72,
            difficulty="regular",
            success_level="failure",
            passed=False,
        ),
        visible_facts=(
            VisibleFact(
                id="action:listen-carefully:direct:result:1",
                text="你在这次尝试中没能充分发挥相应技巧。",
            ),
        ),
        narration_constraints=("检定未通过；不得声称发现新的隐藏信息。",),
        view_revision="0",
    )
    client = ImmersionPromptCaptureClient()

    await PromptNarrationModel(client).generate(
        NarrationContext(
            background="安静、克制的调查故事。",
            player_input=player_input,
            intent=intent,
            action_result=action_result,
            player_view=player_view,
            recent_history=RecentTurnContext.empty(
                player_input=player_input,
                player_view=player_view,
            ),
        )
    )

    serialized = client.inputs["trpg_narration"]
    assert serialized["intent"]["check"]["route"] == "default"
    assert serialized["intent"]["target"]["id"] == "quiet_room"
    assert serialized["action_result"]["outcome"] == "failure"
    assert serialized["action_result"]["check_result"] == {
        "checkpoint_id": None,
        "skill_id": "listen",
        "target_value": 40,
        "roll_value": 72,
        "difficulty": "regular",
        "success_level": "failure",
        "passed": False,
    }


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
