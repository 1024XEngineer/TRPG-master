from typing import Any

import pytest
from collaboration_framework.contracts import JsonObject
from pydantic import ValidationError

from app.adapters.character_background import DeepSeekCharacterBackgroundComposer
from app.core.config import Settings
from app.dto.character_background import CharacterBackgroundContext, CharacterBackgroundSkill
from app.service.character_background import (
    CharacterBackgroundService,
    build_character_background_service,
)


class RecordingJsonClient:
    def __init__(self, result: JsonObject | None = None, error: Exception | None = None) -> None:
        self.result = result or {}
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def generate(
        self,
        *,
        schema_name: str,
        schema: JsonObject,
        instructions: str,
        input_payload: JsonObject,
    ) -> JsonObject:
        self.calls.append(
            {
                "schema_name": schema_name,
                "schema": schema,
                "instructions": instructions,
                "input_payload": input_payload,
            }
        )
        if self.error is not None:
            raise self.error
        return self.result


def make_context() -> CharacterBackgroundContext:
    return CharacterBackgroundContext(
        name="顾宁",
        age=31,
        gender="女",
        residence="阿卡姆",
        birthplace="波士顿",
        occupation="私家侦探",
        occupation_description="受雇调查疑难事件。",
        occupation_categories=["执法安全"],
        attributes={"STR": 45, "INT": 75},
        prominent_skills=[CharacterBackgroundSkill(id="spot-hidden", name="侦查", value=70)],
        credit_rating=30,
        equipment=["笔记本"],
    )


def model_result() -> JsonObject:
    return {
        "equipment": ["笔记本", "手电筒", "笔记本"],
        "personalDescription": "衣着利落，观察周围时十分专注。",
        "ideologyBeliefs": "相信真相总会留下痕迹。",
        "significantPeople": "一位教会她谨慎求证的旧同事。",
        "meaningfulLocations": "常去整理案件记录的安静办公室。",
        "treasuredPossessions": "一本写满旧案线索的笔记本。",
        "traits": "冷静细致，但很难放下未解之谜。",
        "injuriesScars": "右手腕留有一道不显眼的旧伤。",
        "phobiasManias": "紧张时会反复确认门窗是否锁好。",
        "other": "说话前习惯先整理手边的纸张。",
    }


@pytest.mark.asyncio
async def test_deepseek_composer_uses_structured_safe_context() -> None:
    client = RecordingJsonClient(model_result())
    composer = DeepSeekCharacterBackgroundComposer(client)

    draft = await composer.compose(make_context())

    assert draft.personal_description.startswith("衣着利落")
    assert draft.equipment == ["笔记本", "手电筒"]
    call = client.calls[0]
    assert call["schema_name"] == "character_background"
    assert call["input_payload"]["name"] == "顾宁"
    assert "reconnectToken" not in call["input_payload"]
    assert "module" not in call["input_payload"]


@pytest.mark.asyncio
async def test_background_sections_and_equipment_can_be_empty() -> None:
    composer = DeepSeekCharacterBackgroundComposer(
        RecordingJsonClient({"personalDescription": "保持沉默的调查员。"})
    )

    draft = await composer.compose(make_context())

    assert draft.personal_description == "保持沉默的调查员。"
    assert draft.ideology_beliefs == ""
    assert draft.equipment == []
    assert draft.to_character_background() == "形象描述：保持沉默的调查员。"


@pytest.mark.asyncio
async def test_background_service_formats_all_sections() -> None:
    service = CharacterBackgroundService(
        DeepSeekCharacterBackgroundComposer(RecordingJsonClient(model_result()))
    )

    generation = await service.generate(
        make_context(), fallback="固定背景", fallback_equipment=["固定物品"]
    )

    assert generation.background.startswith("形象描述：衣着利落")
    assert "思想与信念：相信真相总会留下痕迹。" in generation.background
    assert "恐惧症和躁狂症：紧张时会反复确认门窗是否锁好。" in generation.background
    assert "其他：说话前习惯先整理手边的纸张。" in generation.background
    assert generation.equipment == ["笔记本", "手电筒"]
    assert len(generation.background) <= 4000


@pytest.mark.asyncio
async def test_background_service_falls_back_on_model_error() -> None:
    client = RecordingJsonClient(error=TimeoutError("provider timeout"))
    service = CharacterBackgroundService(DeepSeekCharacterBackgroundComposer(client))

    generation = await service.generate(
        make_context(), fallback="固定背景", fallback_equipment=["固定物品"]
    )
    assert generation.background == "固定背景"
    assert generation.equipment == ["固定物品"]


@pytest.mark.asyncio
async def test_background_service_falls_back_on_invalid_output() -> None:
    client = RecordingJsonClient({"equipment": "不是列表"})
    service = CharacterBackgroundService(DeepSeekCharacterBackgroundComposer(client))

    generation = await service.generate(
        make_context(), fallback="固定背景", fallback_equipment=["固定物品"]
    )
    assert generation.background == "固定背景"
    assert generation.equipment == ["固定物品"]


def test_deepseek_background_provider_requires_key() -> None:
    with pytest.raises(ValidationError, match="CHARACTER_BACKGROUND_PROVIDER"):
        Settings(
            _env_file=None,
            character_background_provider="deepseek",
            deepseek_api_key=None,
        )


def test_deterministic_background_provider_needs_no_key() -> None:
    service = build_character_background_service(
        Settings(
            _env_file=None,
            character_background_provider="deterministic",
            deepseek_api_key=None,
        )
    )
    assert isinstance(service, CharacterBackgroundService)
