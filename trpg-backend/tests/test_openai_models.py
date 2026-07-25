from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from collaboration_framework.contracts import (
    ActionResult,
    Intent,
    ModuleContent,
    PlayerInput,
    PlayerView,
    VisibleEntity,
    VisibleFact,
)
from collaboration_framework.engine import (
    ActorResources,
    ActorState,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
    RuleKernel,
    SequenceDiceSource,
)
from collaboration_framework.host.schemas import IntentContext, NarrationContext
from pydantic import ValidationError

from app.adapters.openai_models import (
    OpenAIResponsesJsonClient,
    PromptIntentModel,
    PromptNarrationModel,
)
from app.adapters.qwen_models import QwenChatCompletionsJsonClient
from app.core.config import Settings
from app.core.turn import build_turn_application

ROOT = Path(__file__).resolve().parents[2]


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
    entities["douglas"]["willing_to_talk"] = True
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
                checkpoint_id = "talk_to_douglas"
            return {
                "kind": "action",
                "verb": verb,
                "target": {"matched": True, "id": "douglas"},
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
        scene_id="client_briefing",
        phase="playing",
        revision="0",
        visible_entities=(
            VisibleEntity(
                id="thomas",
                kind="npc",
                name="托马斯·金博尔",
                aliases=("托马斯",),
                content="委托调查员寻找五本失窃藏书。",
            ),
        ),
    )
    client = ImmersionPromptCaptureClient()
    intent_payload = await PromptIntentModel(client).generate(
        IntentContext(player_input=player_input, player_view=player_view)
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
        )
    )

    intent_instructions = client.instructions["trpg_intent"]
    narration_instructions = client.instructions["trpg_narration"]
    assert "属于场景定位" in intent_instructions
    assert "感知请求" in intent_instructions
    assert "不要称它为元游戏问题" in intent_instructions
    assert "根据 PlayerView 直接给出" in narration_instructions
    assert "一段场景描述" in narration_instructions
    assert "不要要求玩家先指定目标或先做检定" in narration_instructions
    assert "不得借此创造门窗、出口、人物、物品、路线" in narration_instructions
    assert client.inputs["trpg_narration"]["player_view"]["visible_entities"][0]["id"] == "thomas"
    assert narration["kind"] == "narration"
    assert narration["claimed_fact_ids"] == []


async def test_prompt_models_complete_paper_chase_ending_without_state_access() -> None:
    module = load_paper_chase()
    state = conversation_state(module)
    store = InMemoryEngineStore()
    store.register_room(module_content=module, initial_state=state)
    engine = RuleEngineService(
        store,
        kernel=RuleKernel(
            dice_source=SequenceDiceSource([4, 2]),
            allow_legacy_missing_skill=False,
        ),
    )
    client = ScriptedStructuredClient()
    application = build_turn_application(
        store,
        engine,
        intent_model=PromptIntentModel(client),
        narration_model=PromptNarrationModel(client),
    )

    first = await application.handle(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="talk",
        utterance="我礼貌询问道格拉斯事情的真相",
    )
    second = await application.handle(
        room_id=state.room_id,
        player_id="player_1",
        client_action_id="leave",
        utterance="让道格拉斯离开",
    )

    final_state = store.inspect_state(state.room_id)
    assert first.message_type == second.message_type == "turn.completed"
    assert final_state.phase == "ended"
    assert final_state.ending_id == "ending_douglas_departs"
    assert client.backgrounds == [module.background, module.background]


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


def test_intent_schema_remains_strict_for_prompt_adapter() -> None:
    schema = Intent.model_json_schema(mode="serialization")
    assert schema["additionalProperties"] is False
