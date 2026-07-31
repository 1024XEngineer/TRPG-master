import asyncio
import json
from collections.abc import Callable, Generator
from typing import cast

import httpx
import pytest
from httpx import AsyncClient

from app.adapters.image_generation import DashScopeImageProvider, MockImageProvider
from app.adapters.portrait_prompt import DeepSeekPortraitPromptComposer
from app.core.coc7_content import build_coc7_ruleset
from app.core.seed import BUILTIN_MODULE_ID
from app.dto.portrait import CharacterPortraitSnapshot, PortraitPrompt, PortraitSkillSnapshot
from app.main import app
from app.models.room import Character
from app.service.portrait_generation import (
    DeterministicPromptComposer,
    ImageGenerationOutput,
    PortraitGenerationService,
    PortraitImageContentRejectedError,
    PortraitImageGenerationError,
    PortraitImageTimeoutError,
    _visual_traits,
    build_character_portrait_snapshot,
)
from tests.helpers import ROOMS_BASE, create_room, join_room, reconnect, register

ATTRIBUTES = {
    "STR": 70,
    "CON": 60,
    "POW": 55,
    "DEX": 45,
    "APP": 70,
    "SIZ": 60,
    "INT": 60,
    "EDU": 60,
    "LUCK": 50,
}
SKILLS = {"law": 55, "spot-hidden": 75, "credit-rating": 25}
EQUIPMENT = [{"name": "左轮手枪"}, {"name": "手电筒"}]
BACKGROUND = "黑色短发，右眉有一道浅色伤疤，总是穿着深色风衣。"
MODULE_BACKGROUND = "禁酒令时期的密歇根州，安静克制并带有哥特气息。"
PRIVATE_NOTES = "这是玩家私人备忘，不得发给模型。"
BUILT_CHARACTER: dict[str, object] = {
    "name": "陈探员",
    "age": 34,
    "gender": "男",
    "residence": "阿卡姆",
    "birthplace": "波士顿",
    "attributes": ATTRIBUTES,
    "derivedStats": {"HP": 12, "SAN": 55, "MP": 11},
    "skills": SKILLS,
    "equipment": EQUIPMENT,
    "occupation": "私家侦探",
    "background": BACKGROUND,
    "notes": PRIVATE_NOTES,
}


class FixedPromptComposer:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.snapshots: list[CharacterPortraitSnapshot] = []

    async def compose(self, snapshot: CharacterPortraitSnapshot) -> PortraitPrompt:
        self.snapshots.append(snapshot)
        if self.error is not None:
            raise self.error
        return PortraitPrompt(
            positive_prompt="一名穿深色风衣的侦探",
            negative_prompt="文字，水印",
            prompt_summary="职业与背景形象",
            source="deepseek",
        )


class RecordingImageProvider:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    async def generate(
        self, *, prompt: str, negative_prompt: str, size: str
    ) -> ImageGenerationOutput:
        self.calls.append({"prompt": prompt, "negative_prompt": negative_prompt, "size": size})
        return ImageGenerationOutput(image_url="https://images.example/portrait.png")


class BlockingImageProvider(RecordingImageProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(
        self, *, prompt: str, negative_prompt: str, size: str
    ) -> ImageGenerationOutput:
        self.started.set()
        await self.release.wait()
        return await super().generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            size=size,
        )


@pytest.fixture
def install_portrait_service() -> Generator[
    Callable[[PortraitGenerationService], None], None, None
]:
    previous = app.state.portrait_generation_service

    def install(service: PortraitGenerationService) -> None:
        app.state.portrait_generation_service = service

    yield install
    app.state.portrait_generation_service = previous


def make_service(
    *, enabled: bool = True, prompt_error: Exception | None = None
) -> tuple[PortraitGenerationService, FixedPromptComposer, RecordingImageProvider]:
    composer = FixedPromptComposer(error=prompt_error)
    image_provider = RecordingImageProvider()
    service = PortraitGenerationService(
        enabled=enabled,
        prompt_composer=composer,
        fallback_prompt_composer=DeterministicPromptComposer(),
        image_provider=image_provider,
    )
    return service, composer, image_provider


async def create_character(client: AsyncClient, room: dict, *, complete: bool) -> str:
    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters",
        headers=reconnect(room["reconnectToken"]),
    )
    character_id = draft.json()["data"]["characterId"]
    saved = await client.patch(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}",
        json=BUILT_CHARACTER,
        headers=reconnect(room["reconnectToken"]),
    )
    assert saved.status_code == 200
    if complete:
        completed = await client.post(
            f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/complete",
            headers=reconnect(room["reconnectToken"]),
        )
        assert completed.status_code == 200
    return character_id


def test_snapshot_uses_actual_allocations_and_excludes_notes() -> None:
    character = Character(
        id="00000000-0000-0000-0000-000000000001",
        room_id="00000000-0000-0000-0000-000000000002",
        player_id="00000000-0000-0000-0000-000000000003",
        status="complete",
        name="陈探员",
        age=34,
        gender="男",
        residence="阿卡姆",
        birthplace="波士顿",
        attributes=ATTRIBUTES,
        derived_stats={"HP": 12, "SAN": 55, "MP": 11},
        skills=SKILLS,
        equipment=[item["name"] for item in EQUIPMENT],
        occupation="私家侦探",
        background=BACKGROUND,
        notes=PRIVATE_NOTES,
    )

    snapshot = build_character_portrait_snapshot(
        character,
        build_coc7_ruleset(),
        module_background=MODULE_BACKGROUND,
    )
    serialized = snapshot.model_dump_json()

    assert [skill.id for skill in snapshot.prominent_skills] == [
        "spot-hidden",
        "law",
        "credit-rating",
    ]
    assert snapshot.prominent_skills[0].allocated == 50
    assert "体格强健，肌肉感明显" in snapshot.visual_traits
    assert "外貌与人格吸引力突出" in snapshot.visual_traits
    assert snapshot.occupation_description
    assert BACKGROUND in serialized
    assert snapshot.module_background == MODULE_BACKGROUND
    assert PRIVATE_NOTES not in serialized


def test_visual_traits_keep_attribute_meanings_separate() -> None:
    traits = _visual_traits(
        {
            "STR": 20,
            "CON": 80,
            "SIZ": 80,
            "DEX": 20,
            "APP": 20,
            "POW": 80,
            "INT": 99,
            "EDU": 99,
            "LUCK": 99,
        }
    )

    assert "肌肉感不明显，力量感较弱" in traits
    assert "气色健康，精力充沛" in traits
    assert "体型较大，身形高大" in traits
    assert "动作略显僵硬，身体控制力较弱" in traits
    assert "外在吸引力较弱，气质朴素低调" in traits
    assert "目光坚定，意志感强烈" in traits
    assert len(traits) == 6


async def test_deterministic_prompt_changes_with_portrait_relevant_attributes() -> None:
    composer = DeterministicPromptComposer()
    base = CharacterPortraitSnapshot(character_id="character-1", name="A", attributes={})
    base_prompt = await composer.compose(base)
    variants = [
        base.model_copy(update={"occupation": "记者"}),
        base.model_copy(update={"background": "黑色短发，眉间有一道浅色伤疤"}),
        base.model_copy(update={"module_background": MODULE_BACKGROUND}),
        base.model_copy(update={"equipment": ["相机"]}),
        base.model_copy(
            update={"attributes": {"STR": 80}, "visual_traits": ["体格强健，肌肉感明显"]}
        ),
        base.model_copy(
            update={
                "prominent_skills": [
                    PortraitSkillSnapshot(id="spot-hidden", name="侦察", value=75, allocated=50)
                ]
            }
        ),
    ]

    for variant in variants:
        changed_prompt = await composer.compose(variant)
        assert changed_prompt.positive_prompt != base_prompt.positive_prompt
    assert "写实方形半身单人肖像" in base_prompt.positive_prompt
    assert "多人画面" in base_prompt.negative_prompt


async def test_deepseek_prompt_composer_validates_structured_output() -> None:
    class FakeClient:
        async def generate(self, **kwargs: object) -> dict:
            assert "notes" not in json.dumps(kwargs, ensure_ascii=False)
            input_payload = cast(dict[str, object], kwargs["input_payload"])
            assert input_payload["moduleBackground"] == MODULE_BACKGROUND
            return {
                "positivePrompt": "一名写实风格的私家侦探半身肖像",
                "negativePrompt": "文字，水印",
                "promptSummary": "私家侦探的风衣与手电筒",
            }

    result = await DeepSeekPortraitPromptComposer(FakeClient()).compose(  # type: ignore[arg-type]
        CharacterPortraitSnapshot(
            character_id="character-1",
            name="陈探员",
            module_background=MODULE_BACKGROUND,
        )
    )

    assert result.source == "deepseek"
    assert result.positive_prompt.startswith("一名写实风格")


async def test_deepseek_prompt_composer_rejects_invalid_structure() -> None:
    class FakeClient:
        async def generate(self, **_kwargs: object) -> dict:
            return {"positivePrompt": "missing required fields"}

    with pytest.raises(ValueError):
        await DeepSeekPortraitPromptComposer(FakeClient()).compose(  # type: ignore[arg-type]
            CharacterPortraitSnapshot(character_id="character-1", name="陈探员")
        )


async def test_deepseek_prompt_composer_rejects_non_chinese_prompts() -> None:
    class FakeClient:
        async def generate(self, **_kwargs: object) -> dict:
            return {
                "positivePrompt": "A realistic private detective portrait，中文",
                "negativePrompt": "text, watermark，水印",
                "promptSummary": "English-only summary，中文",
            }

    with pytest.raises(ValueError):
        await DeepSeekPortraitPromptComposer(FakeClient()).compose(  # type: ignore[arg-type]
            CharacterPortraitSnapshot(character_id="character-1", name="陈探员")
        )


@pytest.mark.parametrize(
    "prompt_error",
    [ValueError("invalid model output"), TimeoutError("prompt timeout")],
    ids=["invalid-output", "timeout"],
)
async def test_completed_character_generates_real_provider_result_and_prompt_fallback(
    prompt_error: Exception,
    client: AsyncClient,
    install_portrait_service: Callable[[PortraitGenerationService], None],
) -> None:
    room = await create_room(client, max_players=1)
    selected = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": BUILTIN_MODULE_ID, "attributeGenMethod": "point_buy"},
        headers=reconnect(room["reconnectToken"]),
    )
    assert selected.status_code == 200
    character_id = await create_character(client, room, complete=True)
    service, composer, image_provider = make_service(prompt_error=prompt_error)
    install_portrait_service(service)

    assert composer.snapshots == []
    assert image_provider.calls == []

    response = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations",
        json={"style": "realistic", "size": "1024x1024"},
        headers=reconnect(room["reconnectToken"]),
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["imageUrl"] == "https://images.example/portrait.png"
    assert data["promptSource"] == "deterministic_fallback"
    assert image_provider.calls[0]["size"] == "1024x1024"
    assert composer.snapshots[0].background == BACKGROUND
    assert "禁酒令时期" in composer.snapshots[0].module_background
    assert PRIVATE_NOTES not in composer.snapshots[0].model_dump_json()


async def test_concurrent_portrait_request_is_rejected_before_second_provider_call(
    client: AsyncClient,
    install_portrait_service: Callable[[PortraitGenerationService], None],
) -> None:
    room = await create_room(client)
    character_id = await create_character(client, room, complete=True)
    image_provider = BlockingImageProvider()
    service = PortraitGenerationService(
        enabled=True,
        prompt_composer=FixedPromptComposer(),
        fallback_prompt_composer=DeterministicPromptComposer(),
        image_provider=image_provider,
    )
    install_portrait_service(service)
    url = f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations"
    headers = reconnect(room["reconnectToken"])

    first_request = asyncio.create_task(client.post(url, json={}, headers=headers))
    await image_provider.started.wait()
    second_response = await client.post(url, json={}, headers=headers)
    image_provider.release.set()
    first_response = await first_request

    assert first_response.status_code == 200
    assert second_response.status_code == 409
    assert second_response.json()["error"]["code"] == "PORTRAIT_GENERATION_IN_PROGRESS"
    assert len(image_provider.calls) == 1


async def test_draft_character_is_rejected_without_calling_provider(
    client: AsyncClient,
    install_portrait_service: Callable[[PortraitGenerationService], None],
) -> None:
    room = await create_room(client)
    character_id = await create_character(client, room, complete=False)
    service, _composer, image_provider = make_service()
    install_portrait_service(service)

    response = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations",
        json={},
        headers=reconnect(room["reconnectToken"]),
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CHARACTER_INCOMPLETE"
    assert image_provider.calls == []


async def test_missing_character_returns_not_found(
    client: AsyncClient,
    install_portrait_service: Callable[[PortraitGenerationService], None],
) -> None:
    room = await create_room(client)
    service, _composer, image_provider = make_service()
    install_portrait_service(service)

    response = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/missing-character/portrait-generations",
        json={},
        headers=reconnect(room["reconnectToken"]),
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"
    assert image_provider.calls == []


async def test_cannot_generate_portrait_for_another_player(
    client: AsyncClient,
    install_portrait_service: Callable[[PortraitGenerationService], None],
) -> None:
    room = await create_room(client)
    character_id = await create_character(client, room, complete=True)
    joined = await join_room(client, room["roomCode"], await register(client))
    service, _composer, image_provider = make_service()
    install_portrait_service(service)

    response = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations",
        json={},
        headers=reconnect(joined["reconnectToken"]),
    )

    assert response.status_code == 403
    assert image_provider.calls == []


async def test_disabled_portrait_feature_does_not_call_provider(
    client: AsyncClient,
    install_portrait_service: Callable[[PortraitGenerationService], None],
) -> None:
    room = await create_room(client)
    character_id = await create_character(client, room, complete=True)
    service, _composer, image_provider = make_service(enabled=False)
    install_portrait_service(service)

    response = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations",
        json={},
        headers=reconnect(room["reconnectToken"]),
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PORTRAIT_GENERATION_DISABLED"
    assert image_provider.calls == []


async def test_dashscope_provider_submits_and_polls_task() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": "task-1"}})
        return httpx.Response(
            200,
            json={
                "output": {
                    "task_status": "SUCCEEDED",
                    "results": [{"url": "https://dashscope.example/portrait.png"}],
                }
            },
        )

    provider = DashScopeImageProvider(
        api_key="test-key",
        base_url="https://dashscope.example/api/v1",
        model="wan2.2-t2i-flash",
        timeout_seconds=5,
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    output = await provider.generate(
        prompt="portrait prompt",
        negative_prompt="watermark",
        size="1024x1024",
    )

    submitted = json.loads(requests[0].content)
    assert requests[0].headers["authorization"] == "Bearer test-key"
    assert requests[0].headers["x-dashscope-async"] == "enable"
    assert submitted["model"] == "wan2.2-t2i-flash"
    assert submitted["parameters"] == {"size": "1024*1024", "n": 1}
    assert output.image_url == "https://dashscope.example/portrait.png"


async def test_mock_image_provider_returns_stable_inline_image() -> None:
    provider = MockImageProvider()

    first = await provider.generate(prompt="portrait one", negative_prompt="text", size="1024x1024")
    repeated = await provider.generate(
        prompt="portrait one", negative_prompt="text", size="1024x1024"
    )
    different = await provider.generate(
        prompt="portrait two", negative_prompt="text", size="1024x1024"
    )

    assert first.image_url.startswith("data:image/svg+xml;base64,")
    assert repeated.image_url == first.image_url
    assert different.image_url != first.image_url


async def test_dashscope_provider_maps_content_rejection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            return httpx.Response(200, json={"output": {"task_id": "task-1"}})
        return httpx.Response(
            200,
            json={
                "output": {
                    "task_status": "FAILED",
                    "code": "DataInspectionFailed",
                    "message": "sensitive content",
                }
            },
        )

    provider = DashScopeImageProvider(
        api_key="test-key",
        base_url="https://dashscope.example/api/v1",
        model="wan2.2-t2i-flash",
        timeout_seconds=5,
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PortraitImageContentRejectedError):
        await provider.generate(prompt="prompt", negative_prompt="negative", size="1024x1024")


async def test_dashscope_provider_maps_upstream_http_error() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"message": "temporarily unavailable"})

    provider = DashScopeImageProvider(
        api_key="test-key",
        base_url="https://dashscope.example/api/v1",
        model="wan2.2-t2i-flash",
        timeout_seconds=5,
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PortraitImageGenerationError):
        await provider.generate(prompt="prompt", negative_prompt="negative", size="1024x1024")


async def test_dashscope_provider_times_out_before_polling() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"output": {"task_id": "task-1"}})

    provider = DashScopeImageProvider(
        api_key="test-key",
        base_url="https://dashscope.example/api/v1",
        model="wan2.2-t2i-flash",
        timeout_seconds=0,
        poll_interval_seconds=0,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PortraitImageTimeoutError):
        await provider.generate(prompt="prompt", negative_prompt="negative", size="1024x1024")
