from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from collaboration_framework.contracts import Intent, ModuleContent
from collaboration_framework.engine import (
    ActorResources,
    ActorState,
    GameState,
    InMemoryEngineStore,
    RuleEngineService,
    RuleKernel,
    SequenceDiceSource,
)
from pydantic import ValidationError

from app.adapters.openai_models import (
    OpenAIResponsesJsonClient,
    PromptIntentModel,
    PromptNarrationModel,
)
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


def test_openai_provider_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="OPENAI_API_KEY"):
        Settings.model_validate(
            {
                "host_model_provider": "openai",
                "openai_api_key": None,
            }
        )


def test_intent_schema_remains_strict_for_prompt_adapter() -> None:
    schema = Intent.model_json_schema(mode="serialization")
    assert schema["additionalProperties"] is False
