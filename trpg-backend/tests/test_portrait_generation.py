import asyncio
import base64
import json
from collections.abc import Callable, Generator
from contextlib import suppress
from hashlib import sha256
from io import BytesIO
from typing import cast

import httpx
import pytest
from httpx import AsyncClient
from PIL import Image
from pydantic import ValidationError

from app.adapters.image_generation import (
    DashScopeImageProvider,
    MockImageProvider,
    SufyImageProvider,
)
from app.adapters.portrait_prompt import DeepSeekPortraitPromptComposer
from app.core.coc7_content import build_coc7_ruleset
from app.core.config import Settings
from app.core.seed import BUILTIN_MODULE_ID, BUILTIN_SYSTEM_ID
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
    build_portrait_generation_service,
)
from app.service.portrait_image import MaterializedPortraitImage, PortraitImageMaterializer
from app.service.portrait_reference import PortraitReferenceImage, load_portrait_reference_image
from tests.helpers import ROOMS_BASE, bearer, create_room, join_room, reconnect, register

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
        self,
        *,
        prompt: str,
        negative_prompt: str,
        size: str,
        reference_image: PortraitReferenceImage | None = None,
    ) -> ImageGenerationOutput:
        self.calls.append({"prompt": prompt, "negative_prompt": negative_prompt, "size": size})
        return ImageGenerationOutput(image_url="https://images.example/portrait.png")


class FixedImageMaterializer:
    """接口测试使用的确定性物化器，避免访问真实图片服务。"""

    def __init__(self, content: bytes = b"persisted-png") -> None:
        self.content = content
        self.calls: list[str] = []

    async def materialize(self, image_url: str) -> MaterializedPortraitImage:
        self.calls.append(image_url)
        return MaterializedPortraitImage(
            content=self.content,
            content_type="image/png",
            content_hash=sha256(self.content).hexdigest(),
        )


class FailingImageMaterializer:
    async def materialize(self, image_url: str) -> MaterializedPortraitImage:
        del image_url
        raise PortraitImageGenerationError("图片下载失败")


def png_bytes(*, width: int = 32, height: int = 32, color: str = "#204b5e") -> bytes:
    """生成测试专用的小型 PNG，确保物化器覆盖真实 Pillow 解码路径。"""
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


class BlockingImageProvider(RecordingImageProvider):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def generate(
        self,
        *,
        prompt: str,
        negative_prompt: str,
        size: str,
        reference_image: PortraitReferenceImage | None = None,
    ) -> ImageGenerationOutput:
        self.started.set()
        await self.release.wait()
        return await super().generate(
            prompt=prompt,
            negative_prompt=negative_prompt,
            size=size,
        )


class CancelIgnoringImageProvider(BlockingImageProvider):
    """模拟无法终止的上游：吞掉本地取消并返回迟到结果。"""

    async def generate(self, **kwargs: object) -> ImageGenerationOutput:
        self.started.set()
        with suppress(asyncio.CancelledError):
            await self.release.wait()
        self.calls.append({"prompt": str(kwargs.get("prompt", ""))})
        return ImageGenerationOutput(image_url="https://images.example/late.png")


@pytest.fixture
def install_portrait_service() -> Generator[
    Callable[[PortraitGenerationService], None], None, None
]:
    previous = app.state.portrait_generation_service

    def install(service: PortraitGenerationService) -> None:
        service.set_session_factory_for_testing(app.state.test_session_factory)
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
        image_materializer=FixedImageMaterializer(),
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


async def wait_for_generation(
    client: AsyncClient, url: str, headers: dict[str, str], generation_id: str
) -> dict[str, object]:
    """轮询后台任务到终态，避免测试依赖协程调度时序。"""
    for _ in range(100):
        response = await client.get(f"{url}/{generation_id}", headers=headers)
        data = response.json()["data"]
        if data["status"] in {"completed", "failed", "cancelled"}:
            return data
        await asyncio.sleep(0.01)
    raise AssertionError("生图任务未在测试时限内结束")


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
    assert "偏漫画风格" in base_prompt.positive_prompt
    assert "背景自然延伸至四边" in base_prompt.positive_prompt
    assert "照片写实" in base_prompt.negative_prompt
    assert "卡纸" in base_prompt.negative_prompt
    assert "画中画" in base_prompt.negative_prompt
    assert "写实肖像" not in base_prompt.prompt_summary
    assert "多人画面" in base_prompt.negative_prompt


def test_portrait_reference_loader_returns_private_data_uri() -> None:
    reference = load_portrait_reference_image("app/assets/portrait-style-reference.png")

    assert reference is not None
    assert reference.mime_type == "image/png"
    assert reference.filename == "portrait-style-reference.png"
    assert reference.data_uri.startswith("data:image/png;base64,")


def test_portrait_reference_loader_rejects_missing_or_invalid_files(tmp_path) -> None:
    missing = load_portrait_reference_image(str(tmp_path / "missing.png"))
    invalid_path = tmp_path / "reference.txt"
    invalid_path.write_text("not an image", encoding="utf-8")

    assert missing is None
    assert load_portrait_reference_image(str(invalid_path)) is None


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
    headers = reconnect(room["reconnectToken"])

    assert composer.snapshots == []
    assert image_provider.calls == []

    response = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations",
        json={"style": "realistic", "size": "1024x1024"},
        headers=headers,
    )

    assert response.status_code == 202
    queued = response.json()["data"]
    assert queued["status"] == "queued"
    data = await wait_for_generation(
        client,
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations",
        headers,
        queued["generationId"],
    )
    assert data["portraitVersion"] == sha256(b"persisted-png").hexdigest()
    assert data["promptSource"] == "deterministic_fallback"
    assert image_provider.calls[0]["size"] == "1024x1024"
    assert composer.snapshots[0].background == BACKGROUND
    assert "禁酒令时期" in composer.snapshots[0].module_background
    assert PRIVATE_NOTES not in composer.snapshots[0].model_dump_json()

    portrait = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/players/{room['playerId']}/portrait",
        headers=headers,
    )
    assert portrait.status_code == 200
    assert portrait.content == b"persisted-png"
    assert portrait.headers["content-type"] == "image/png"
    assert portrait.headers["cache-control"] == "private, max-age=3600"
    assert portrait.headers["x-content-type-options"] == "nosniff"
    assert portrait.headers["etag"] == f'"{data["portraitVersion"]}"'

    not_modified = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/players/{room['playerId']}/portrait",
        headers={**headers, "If-None-Match": f'W/"{data["portraitVersion"]}"'},
    )
    stale_cache = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/players/{room['playerId']}/portrait",
        headers={**headers, "If-None-Match": '"stale-version"'},
    )
    assert not_modified.status_code == 304
    assert not_modified.content == b""
    assert not_modified.headers["etag"] == f'"{data["portraitVersion"]}"'
    assert stale_cache.status_code == 200
    assert stale_cache.content == b"persisted-png"

    preview = await client.get(f"{ROOMS_BASE}/{room['roomCode']}")
    player = next(
        item for item in preview.json()["data"]["players"] if item["playerId"] == room["playerId"]
    )
    assert player["hasPortrait"] is True
    assert player["portraitVersion"] == data["portraitVersion"]


async def test_template_derived_generation_updates_library_and_next_room(
    client: AsyncClient,
    install_portrait_service: Callable[[PortraitGenerationService], None],
) -> None:
    token = await register(client)
    template_response = await client.post(
        "/api/v1/me/character-templates",
        json={
            "name": "陈探员",
            "systemId": BUILTIN_SYSTEM_ID,
            "data": {
                "name": BUILT_CHARACTER["name"],
                "age": BUILT_CHARACTER["age"],
                "gender": BUILT_CHARACTER["gender"],
                "residence": BUILT_CHARACTER["residence"],
                "birthplace": BUILT_CHARACTER["birthplace"],
                "attributes": BUILT_CHARACTER["attributes"],
                "skills": BUILT_CHARACTER["skills"],
                "equipment": ["左轮手枪", "手电筒"],
                "occupation": BUILT_CHARACTER["occupation"],
                "background": BUILT_CHARACTER["background"],
                "notes": BUILT_CHARACTER["notes"],
            },
        },
        headers=bearer(token),
    )
    assert template_response.status_code == 201, template_response.text
    template_id = template_response.json()["data"]["templateId"]

    room = await create_room(client, token=token, max_players=1)
    selected = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/module",
        json={"moduleId": BUILTIN_MODULE_ID, "attributeGenMethod": "point_buy"},
        headers=reconnect(room["reconnectToken"]),
    )
    assert selected.status_code == 200
    draft = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters",
        json={"basedOnTemplateId": template_id},
        headers=reconnect(room["reconnectToken"]),
    )
    assert draft.status_code == 201, draft.text
    character_id = draft.json()["data"]["characterId"]
    completed = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/complete",
        headers=reconnect(room["reconnectToken"]),
    )
    assert completed.status_code == 200, completed.text

    service, _composer, _provider = make_service()
    install_portrait_service(service)
    generation_url = f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations"
    created = await client.post(generation_url, json={}, headers=reconnect(room["reconnectToken"]))
    terminal = await wait_for_generation(
        client,
        generation_url,
        reconnect(room["reconnectToken"]),
        created.json()["data"]["generationId"],
    )
    assert terminal["status"] == "completed"

    listed = await client.get("/api/v1/me/character-templates", headers=bearer(token))
    template = next(item for item in listed.json()["data"] if item["templateId"] == template_id)
    assert template["hasPortrait"] is True
    assert template["portraitVersion"] == terminal["portraitVersion"]
    template_portrait = await client.get(
        f"/api/v1/me/character-templates/{template_id}/portrait",
        headers=bearer(token),
    )
    assert template_portrait.content == b"persisted-png"

    replacement_service = PortraitGenerationService(
        enabled=True,
        prompt_composer=FixedPromptComposer(),
        fallback_prompt_composer=DeterministicPromptComposer(),
        image_provider=RecordingImageProvider(),
        image_materializer=FixedImageMaterializer(b"regenerated-png"),
    )
    install_portrait_service(replacement_service)
    regenerated = await client.post(
        generation_url,
        json={},
        headers=reconnect(room["reconnectToken"]),
    )
    regenerated_terminal = await wait_for_generation(
        client,
        generation_url,
        reconnect(room["reconnectToken"]),
        regenerated.json()["data"]["generationId"],
    )
    assert regenerated_terminal["portraitVersion"] != terminal["portraitVersion"]
    latest_template_portrait = await client.get(
        f"/api/v1/me/character-templates/{template_id}/portrait",
        headers=bearer(token),
    )
    assert latest_template_portrait.content == b"regenerated-png"

    next_room = await create_room(client, token=token)
    next_draft = await client.post(
        f"{ROOMS_BASE}/{next_room['roomId']}/characters",
        json={"basedOnTemplateId": template_id},
        headers=reconnect(next_room["reconnectToken"]),
    )
    assert next_draft.status_code == 201, next_draft.text
    inherited = await client.get(
        f"{ROOMS_BASE}/{next_room['roomId']}/players/{next_room['playerId']}/portrait",
        headers=reconnect(next_room["reconnectToken"]),
    )
    assert inherited.status_code == 200
    assert inherited.content == b"regenerated-png"


async def test_portrait_read_requires_same_room_membership(
    client: AsyncClient,
    install_portrait_service: Callable[[PortraitGenerationService], None],
) -> None:
    room = await create_room(client)
    character_id = await create_character(client, room, complete=True)
    service, _composer, _provider = make_service()
    install_portrait_service(service)
    generated = await client.post(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations",
        json={},
        headers=reconnect(room["reconnectToken"]),
    )
    assert generated.status_code == 202
    await wait_for_generation(
        client,
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations",
        reconnect(room["reconnectToken"]),
        generated.json()["data"]["generationId"],
    )
    teammate = await join_room(client, room["roomCode"], await register(client))
    other_room = await create_room(client)
    url = f"{ROOMS_BASE}/{room['roomId']}/players/{room['playerId']}/portrait"
    missing_portrait_url = f"{ROOMS_BASE}/{room['roomId']}/players/{teammate['playerId']}/portrait"

    # 条件缓存头不能绕过房间鉴权；即使声称任意版本可用，也必须先验证成员身份。
    missing = await client.get(url, headers={"If-None-Match": "*"})
    allowed = await client.get(url, headers=reconnect(teammate["reconnectToken"]))
    no_portrait = await client.get(
        missing_portrait_url,
        headers=reconnect(room["reconnectToken"]),
    )
    forbidden = await client.get(url, headers=reconnect(other_room["reconnectToken"]))

    assert missing.status_code == 401
    assert allowed.status_code == 200
    assert no_portrait.status_code == 404
    assert forbidden.status_code == 403


async def test_failed_regeneration_keeps_previous_portrait(
    client: AsyncClient,
    install_portrait_service: Callable[[PortraitGenerationService], None],
) -> None:
    room = await create_room(client)
    character_id = await create_character(client, room, complete=True)
    service, _composer, _provider = make_service()
    install_portrait_service(service)
    generation_url = f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations"
    headers = reconnect(room["reconnectToken"])
    first = await client.post(generation_url, json={}, headers=headers)
    assert first.status_code == 202
    await wait_for_generation(client, generation_url, headers, first.json()["data"]["generationId"])

    replacement_content = b"replacement-png"
    replacement_service = PortraitGenerationService(
        enabled=True,
        prompt_composer=FixedPromptComposer(),
        fallback_prompt_composer=DeterministicPromptComposer(),
        image_provider=RecordingImageProvider(),
        image_materializer=FixedImageMaterializer(replacement_content),
    )
    install_portrait_service(replacement_service)
    replaced = await client.post(generation_url, json={}, headers=headers)
    assert replaced.status_code == 202
    await wait_for_generation(
        client, generation_url, headers, replaced.json()["data"]["generationId"]
    )

    failing_service = PortraitGenerationService(
        enabled=True,
        prompt_composer=FixedPromptComposer(),
        fallback_prompt_composer=DeterministicPromptComposer(),
        image_provider=RecordingImageProvider(),
        image_materializer=FailingImageMaterializer(),
    )
    install_portrait_service(failing_service)
    failed = await client.post(generation_url, json={}, headers=headers)
    assert failed.status_code == 202
    failed_task = await wait_for_generation(
        client, generation_url, headers, failed.json()["data"]["generationId"]
    )
    portrait = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/players/{room['playerId']}/portrait",
        headers=headers,
    )

    assert failed_task["status"] == "failed"
    assert failed_task["failureCode"] == "materialization_failed"
    assert portrait.status_code == 200
    assert portrait.content == replacement_content


async def test_portrait_image_materializer_validates_data_uri_and_remote_redirect() -> None:
    content = png_bytes()
    encoded = base64.b64encode(content).decode()
    materializer = PortraitImageMaterializer(max_bytes=1024 * 1024, timeout_seconds=1)

    inline = await materializer.materialize(f"data:image/png;base64,{encoded}")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/start":
            return httpx.Response(302, headers={"Location": "/portrait.png"})
        return httpx.Response(200, content=content, headers={"Content-Type": "image/png"})

    remote = await PortraitImageMaterializer(
        max_bytes=1024 * 1024,
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
        resolve_dns=False,
    ).materialize("https://images.example/start")

    assert inline.content_type == "image/png"
    assert inline.content_hash == sha256(content).hexdigest()
    assert remote == inline


@pytest.mark.parametrize(
    "image_url",
    [
        "data:image/png;base64,not-base64",
        f"data:image/png;base64,{base64.b64encode(b'not-an-image').decode()}",
        "data:image/svg+xml;base64,PHN2Zz48L3N2Zz4=",
        "file:///tmp/portrait.png",
        "http://127.0.0.1/portrait.png",
    ],
)
async def test_portrait_image_materializer_rejects_invalid_or_unsafe_input(
    image_url: str,
) -> None:
    materializer = PortraitImageMaterializer(max_bytes=1024, timeout_seconds=1)
    with pytest.raises(PortraitImageGenerationError):
        await materializer.materialize(image_url)


async def test_portrait_image_materializer_rejects_oversized_dimensions_and_bytes() -> None:
    oversized_dimensions = png_bytes(width=4097, height=1)
    materializer = PortraitImageMaterializer(
        max_bytes=len(oversized_dimensions) + 100,
        timeout_seconds=1,
    )
    with pytest.raises(PortraitImageGenerationError, match="尺寸"):
        await materializer.materialize(
            f"data:image/png;base64,{base64.b64encode(oversized_dimensions).decode()}"
        )

    small_limit = PortraitImageMaterializer(max_bytes=16, timeout_seconds=1)
    with pytest.raises(PortraitImageGenerationError, match="大小"):
        await small_limit.materialize(
            f"data:image/png;base64,{base64.b64encode(png_bytes()).decode()}"
        )


async def test_portrait_image_materializer_maps_remote_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timeout", request=request)

    materializer = PortraitImageMaterializer(
        max_bytes=1024,
        timeout_seconds=1,
        transport=httpx.MockTransport(handler),
        resolve_dns=False,
    )
    with pytest.raises(PortraitImageTimeoutError, match="下载超时"):
        await materializer.materialize("https://images.example/portrait.png")


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
        image_materializer=FixedImageMaterializer(),
    )
    install_portrait_service(service)
    url = f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations"
    headers = reconnect(room["reconnectToken"])

    first_request = asyncio.create_task(client.post(url, json={}, headers=headers))
    await image_provider.started.wait()
    second_response = await client.post(url, json={}, headers=headers)
    image_provider.release.set()
    first_response = await first_request
    await wait_for_generation(client, url, headers, first_response.json()["data"]["generationId"])

    assert first_response.status_code == 202
    assert second_response.status_code == 409
    assert second_response.json()["error"]["code"] == "PORTRAIT_GENERATION_IN_PROGRESS"
    assert len(image_provider.calls) == 1


async def test_current_is_null_before_first_generation(
    client: AsyncClient,
    install_portrait_service: Callable[[PortraitGenerationService], None],
) -> None:
    room = await create_room(client)
    character_id = await create_character(client, room, complete=True)
    service, _composer, _provider = make_service()
    install_portrait_service(service)
    response = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations/current",
        headers=reconnect(room["reconnectToken"]),
    )
    assert response.status_code == 200
    assert response.json()["data"] is None


async def test_cancel_discards_provider_late_result(
    client: AsyncClient,
    install_portrait_service: Callable[[PortraitGenerationService], None],
) -> None:
    room = await create_room(client)
    character_id = await create_character(client, room, complete=True)
    provider = CancelIgnoringImageProvider()
    service = PortraitGenerationService(
        enabled=True,
        prompt_composer=FixedPromptComposer(),
        fallback_prompt_composer=DeterministicPromptComposer(),
        image_provider=provider,
        image_materializer=FixedImageMaterializer(b"late-image"),
    )
    install_portrait_service(service)
    url = f"{ROOMS_BASE}/{room['roomId']}/characters/{character_id}/portrait-generations"
    headers = reconnect(room["reconnectToken"])
    created = await client.post(url, json={}, headers=headers)
    generation_id = created.json()["data"]["generationId"]
    await provider.started.wait()

    cancelled = await client.post(f"{url}/{generation_id}/cancel", headers=headers)
    provider.release.set()
    terminal = await wait_for_generation(client, url, headers, generation_id)

    assert cancelled.status_code == 200
    assert cancelled.json()["data"]["status"] == "cancelling"
    assert terminal["status"] == "cancelled"
    portrait = await client.get(
        f"{ROOMS_BASE}/{room['roomId']}/players/{room['playerId']}/portrait", headers=headers
    )
    assert portrait.status_code == 404


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


async def test_dashscope_provider_cancel_calls_upstream_task_endpoint() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"output": {"task_status": "CANCELED"}})

    provider = DashScopeImageProvider(
        api_key="test-key",
        base_url="https://dashscope.example/api/v1",
        model="wan2.2-t2i-flash",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )
    await provider.cancel("task-1")
    assert requests[0].method == "POST"
    assert requests[0].url.path.endswith("/tasks/task-1/cancel")


async def test_mock_image_provider_returns_stable_inline_image() -> None:
    provider = MockImageProvider()

    first = await provider.generate(prompt="portrait one", negative_prompt="text", size="1024x1024")
    repeated = await provider.generate(
        prompt="portrait one", negative_prompt="text", size="1024x1024"
    )
    different = await provider.generate(
        prompt="portrait two", negative_prompt="text", size="1024x1024"
    )

    assert first.image_url.startswith("data:image/png;base64,")
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


async def test_sufy_provider_submits_openai_compatible_request() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"data": [{"url": "https://sufy.example/portrait.png"}]})

    provider = SufyImageProvider(
        api_key="test-key",
        base_url="https://openai.sufy.example/v1/",
        model="google/gemini-3-pro-image",
        timeout_seconds=120,
        transport=httpx.MockTransport(handler),
    )

    output = await provider.generate(
        prompt="漫画风侦探立绘",
        negative_prompt="写实照片，水印",
        size="1024x1024",
    )

    assert len(requests) == 1
    request = requests[0]
    submitted = json.loads(request.content)
    assert request.url == "https://openai.sufy.example/v1/images/generations"
    assert request.headers["authorization"] == "Bearer test-key"
    assert submitted == {
        "model": "google/gemini-3-pro-image",
        "prompt": "漫画风侦探立绘\n\n避免出现以下内容：写实照片，水印",
        "size": "1024x1024",
        "n": 1,
    }
    assert output.image_url == "https://sufy.example/portrait.png"


async def test_sufy_provider_submits_builtin_reference_image() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"data": [{"url": "https://sufy.example/portrait.png"}]})

    provider = SufyImageProvider(
        api_key="test-key",
        base_url="https://openai.sufy.example/v1",
        model="google/gemini-3-pro-image",
        timeout_seconds=120,
        transport=httpx.MockTransport(handler),
    )
    reference = PortraitReferenceImage(
        content=b"\x89PNG\r\n\x1a\nreference",
        mime_type="image/png",
        filename="portrait-style-reference.png",
    )

    await provider.generate(
        prompt="漫画风格角色立绘",
        negative_prompt="文字",
        size="1024x1024",
        reference_image=reference,
    )

    assert len(requests) == 1
    assert requests[0]["images"] == [reference.data_uri]
    assert "data:image/png;base64," in str(requests[0]["images"])


async def test_sufy_provider_downgrades_once_when_reference_is_unsupported() -> None:
    requests: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        requests.append(payload)
        if "images" in payload:
            return httpx.Response(422, json={"error": {"message": "reference image not supported"}})
        return httpx.Response(200, json={"data": [{"url": "https://sufy.example/portrait.png"}]})

    provider = SufyImageProvider(
        api_key="test-key",
        base_url="https://openai.sufy.example/v1",
        model="google/gemini-3-pro-image",
        timeout_seconds=120,
        transport=httpx.MockTransport(handler),
    )
    reference = PortraitReferenceImage(
        content=b"\x89PNG\r\n\x1a\nreference",
        mime_type="image/png",
        filename="portrait-style-reference.png",
    )

    output = await provider.generate(
        prompt="漫画风格角色立绘",
        negative_prompt="文字",
        size="1024x1024",
        reference_image=reference,
    )

    assert output.image_url == "https://sufy.example/portrait.png"
    assert len(requests) == 2
    assert "images" in requests[0]
    assert "images" not in requests[1]


async def test_sufy_provider_returns_validated_base64_image() -> None:
    encoded = base64.b64encode(b"\x89PNG\r\n\x1a\nportrait").decode()

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"b64_json": encoded}]})

    provider = SufyImageProvider(
        api_key="test-key",
        base_url="https://openai.sufy.example/v1",
        model="google/gemini-3-pro-image",
        timeout_seconds=120,
        transport=httpx.MockTransport(handler),
    )

    output = await provider.generate(prompt="prompt", negative_prompt="negative", size="1024x1024")

    assert output.image_url == f"data:image/png;base64,{encoded}"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data": []},
        {"data": [{"url": "file:///tmp/portrait.png"}]},
        {"data": [{"b64_json": "not-valid-base64"}]},
    ],
)
async def test_sufy_provider_rejects_malformed_image_results(payload: object) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    provider = SufyImageProvider(
        api_key="test-key",
        base_url="https://openai.sufy.example/v1",
        model="google/gemini-3-pro-image",
        timeout_seconds=120,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PortraitImageGenerationError, match="服务暂时不可用"):
        await provider.generate(prompt="prompt", negative_prompt="negative", size="1024x1024")


async def test_sufy_provider_maps_content_rejection_without_exposing_response() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            422,
            json={"error": {"type": "content_policy", "message": "sensitive prompt detail"}},
        )

    provider = SufyImageProvider(
        api_key="test-key",
        base_url="https://openai.sufy.example/v1",
        model="google/gemini-3-pro-image",
        timeout_seconds=120,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PortraitImageContentRejectedError) as error:
        await provider.generate(prompt="prompt", negative_prompt="negative", size="1024x1024")
    assert "sensitive prompt detail" not in str(error.value)


@pytest.mark.parametrize("status_code", [401, 403, 429, 500])
async def test_sufy_provider_maps_upstream_errors_without_exposing_response(
    status_code: int,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code,
            json={"error": {"type": "upstream", "message": "private upstream detail"}},
        )

    provider = SufyImageProvider(
        api_key="test-key",
        base_url="https://openai.sufy.example/v1",
        model="google/gemini-3-pro-image",
        timeout_seconds=120,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PortraitImageGenerationError) as error:
        await provider.generate(prompt="prompt", negative_prompt="negative", size="1024x1024")
    assert "private upstream detail" not in str(error.value)


async def test_sufy_provider_maps_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("upstream timeout", request=request)

    provider = SufyImageProvider(
        api_key="test-key",
        base_url="https://openai.sufy.example/v1",
        model="google/gemini-3-pro-image",
        timeout_seconds=120,
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(PortraitImageTimeoutError):
        await provider.generate(prompt="prompt", negative_prompt="negative", size="1024x1024")


def test_sufy_provider_requires_key_when_portrait_generation_is_enabled() -> None:
    with pytest.raises(ValidationError, match="SUFY_API_KEY"):
        Settings(
            character_portrait_enabled=True,
            portrait_image_provider="sufy",
            sufy_api_key=None,
        )


def test_portrait_service_builds_selected_image_provider() -> None:
    mock_service = build_portrait_generation_service(
        Settings(character_portrait_enabled=True, portrait_image_provider="mock")
    )
    dashscope_service = build_portrait_generation_service(
        Settings(
            character_portrait_enabled=True,
            portrait_image_provider="dashscope",
            dashscope_api_key="test-key",
        )
    )
    sufy_service = build_portrait_generation_service(
        Settings(
            character_portrait_enabled=True,
            portrait_image_provider="sufy",
            sufy_api_key="test-key",
        )
    )
    auto_sufy_service = build_portrait_generation_service(
        Settings(
            character_portrait_enabled=True, portrait_image_provider="auto", sufy_api_key="test-key"
        )
    )
    auto_dashscope_service = build_portrait_generation_service(
        Settings(
            character_portrait_enabled=True,
            portrait_image_provider="auto",
            dashscope_api_key="test-key",
            sufy_api_key=None,
        )
    )
    auto_mock_service = build_portrait_generation_service(
        Settings(character_portrait_enabled=True, portrait_image_provider="auto", sufy_api_key=None)
    )

    assert isinstance(mock_service._image_provider, MockImageProvider)
    assert isinstance(dashscope_service._image_provider, DashScopeImageProvider)
    assert isinstance(sufy_service._image_provider, SufyImageProvider)
    assert isinstance(auto_sufy_service._image_provider, SufyImageProvider)
    assert isinstance(auto_dashscope_service._image_provider, DashScopeImageProvider)
    assert isinstance(auto_mock_service._image_provider, MockImageProvider)
