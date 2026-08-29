"""Issue #220：主持人语音授权、分句、缓存及离线 Provider 集成。"""

import asyncio
import json
import struct
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from httpx import AsyncClient
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.host_speech import (
    DOUBAO_LIST_SPEAKERS_ENDPOINT,
    DoubaoHostSpeechProvider,
    HostSpeechCatalogItem,
    HostSpeechRequest,
    HostSpeechResult,
    _build_doubao_headers,
    parse_server_frame,
)
from app.core.config import HostSpeechVoiceConfig, Settings
from app.main import app
from app.models.event import Event
from app.service.host_speech import (
    HostSpeechService,
    build_host_speech_service,
    get_npc_voice,
    split_narration_for_speech,
)
from tests.helpers import bearer, create_room, join_room, register


def _combined_headers(account_token: str, reconnect_token: str) -> dict[str, str]:
    return {**bearer(account_token), "X-Reconnect-Token": reconnect_token}


def _service(provider) -> HostSpeechService:  # noqa: ANN001
    return HostSpeechService(
        provider,
        voices=[HostSpeechVoiceConfig(voiceType="voice-a", label="音色 A")],
        default_voice_type="voice-a",
        max_sentence_bytes=12,
        cache_ttl_seconds=3600,
        cache_max_bytes=1024,
        player_requests_per_minute=60,
        room_misses_per_minute=30,
        max_concurrency=8,
    )


class _CountingProvider:
    name = "counting"
    version = "counting-v1"
    available = True

    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(self, request: HostSpeechRequest) -> HostSpeechResult:
        self.calls += 1
        # 让两个并发调用都能进入 single-flight 的竞争窗口。
        await asyncio.sleep(0)
        return HostSpeechResult(audio=request.text.encode())


def test_sentence_byte_limit_preserves_authoritative_text() -> None:
    text = "雨落下。门后传来脚步声！\n不要回头。"
    sentences = split_narration_for_speech(text, max_bytes=12)
    assert "".join(sentences) == text
    assert all(len(sentence.encode()) <= 12 for sentence in sentences)


async def test_cache_and_single_flight_share_one_provider_call() -> None:
    provider = _CountingProvider()
    service = _service(provider)
    kwargs = {"room_id": "room", "player_id": "player", "text": "同一句", "voice_type": "voice-a"}
    first, second = await asyncio.gather(service.synthesize(**kwargs), service.synthesize(**kwargs))
    cached = await service.synthesize(**kwargs)
    assert first.audio == second.audio == cached.audio
    assert provider.calls == 1


async def test_doubao_list_speakers_filters_chinese() -> None:
    """ListSpeakers 只把当前资源包返回的中文音色交给业务层。"""

    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "Result": {
                    "Speakers": [
                        {"VoiceType": "zh_female_b", "Name": "女声 B"},
                        {"VoiceType": "en_male_a", "Name": "英文 A"},
                        {"VoiceType": "zh_female_b", "Name": "重复 B"},
                        {"VoiceType": "zh_male_a", "Name": "男声 A"},
                    ]
                }
            },
        )

    provider = DoubaoHostSpeechProvider(
        api_key="api-key",
        resource_id="seed-tts-2.0",
        timeout_seconds=5,
        transport=httpx.MockTransport(handler),
    )
    items = await provider.list_speakers("seed-tts-2.0")
    assert items == (
        HostSpeechCatalogItem("zh_female_b", "女声 B"),
        HostSpeechCatalogItem("zh_male_a", "男声 A"),
    )
    assert requests[0].url == httpx.URL(DOUBAO_LIST_SPEAKERS_ENDPOINT)
    assert requests[0].headers["X-Api-Key"] == "api-key"
    assert json.loads(requests[0].content)["ResourceIDs"] == ["seed-tts-2.0"]


async def test_dynamic_catalog_merges_explicit_voices_and_is_resource_scoped() -> None:
    """动态目录成功时扩展显式配置，资源切换后必须重新读取。"""

    class CatalogProvider(_CountingProvider):
        name = "doubao"

        def __init__(self) -> None:
            super().__init__()
            self.resources: list[str] = []

        async def list_speakers(self, resource_id: str) -> tuple[HostSpeechCatalogItem, ...]:
            self.resources.append(resource_id)
            return (
                HostSpeechCatalogItem("zh_dynamic", "动态音色"),
                HostSpeechCatalogItem("en_dynamic", "英文音色"),
            )

    provider = CatalogProvider()
    service = _service(provider)
    service.resource_id = "seed-tts-2.0"
    await service.refresh_voice_catalog()
    assert service.allowed_voice_types == {"voice-a", "zh_dynamic"}
    assert [voice.voice_type for voice in service.voices] == ["voice-a", "zh_dynamic"]
    await service.refresh_voice_catalog()
    assert provider.resources == ["seed-tts-2.0"]

    service.resource_id = "seed-tts-1.0"
    await service.refresh_voice_catalog()
    assert provider.resources == ["seed-tts-2.0", "seed-tts-1.0"]


async def test_dynamic_catalog_failure_keeps_explicit_voice_allowlist() -> None:
    """豆包目录暂时不可用时，显式配置仍可合成语音。"""

    class FailingCatalogProvider(_CountingProvider):
        name = "doubao"

        async def list_speakers(self, resource_id: str) -> tuple[HostSpeechCatalogItem, ...]:
            del resource_id
            raise RuntimeError("catalog unavailable")

    service = _service(FailingCatalogProvider())
    service.resource_id = "seed-tts-2.0"
    await service.refresh_voice_catalog()
    assert service.allowed_voice_types == {"voice-a"}
    assert service.effective_voice_type("missing") == "voice-a"


def test_invalid_default_voice_makes_audio_unavailable_without_affecting_text() -> None:
    """默认音色失效时不向 Provider 发起请求，但调用方仍可保留文字事件。"""

    service = HostSpeechService(
        _CountingProvider(),
        voices=[HostSpeechVoiceConfig(voiceType="voice-a", label="音色 A")],
        default_voice_type="missing",
        max_sentence_bytes=12,
        cache_ttl_seconds=3600,
        cache_max_bytes=1024,
        player_requests_per_minute=60,
        room_misses_per_minute=30,
        max_concurrency=8,
    )
    assert service.available is False
    assert service.effective_voice_type("missing") is None


async def test_npc_voice_resolves_profile_and_falls_back_on_resource_mismatch() -> None:
    service = _service(_CountingProvider())
    service.resource_id = "seed-tts-2.0"
    fixture = (
        Path(__file__).resolve().parents[2]
        / "agent-collaboration-framework"
        / "docs/module-parser/examples/module-content-validation/追书人/module-content-v3.json"
    )
    module = SimpleNamespace(content_json=json.loads(fixture.read_text(encoding="utf-8")))
    room = SimpleNamespace(scenario_id="scenario", module_version="3.0.10")
    scenario = SimpleNamespace(module_id="paper-chase-zh-coc7", version="3.0.10")

    class FakeDb:
        async def get(self, model, key):
            from app.models.content import Scenario
            from app.models.engine import ModuleVersion
            from app.models.room import Room

            if model is Room:
                return room
            if model is Scenario:
                return scenario
            if model is ModuleVersion:
                return module
            return None

    event = SimpleNamespace(payload={"speakerId": "thomas"}, actor_id="thomas")
    # provider 不匹配时必须回退，而不是把模组中的音色直接交给 Provider。
    assert (
        await get_npc_voice(
            cast(AsyncSession, FakeDb()),
            room_id="room",
            event=cast(Event, event),
            service=service,
        )
        == "voice-a"
    )


def test_doubao_configuration_fails_fast_without_credentials() -> None:
    with pytest.raises(ValidationError):
        Settings(_env_file=None, host_speech_provider="doubao")  # ty: ignore[unknown-argument]


def test_doubao_new_console_configuration_uses_api_key_and_default_resource() -> None:
    settings = Settings(
        _env_file=None,  # ty: ignore[unknown-argument]
        host_speech_provider="doubao",
        doubao_tts_api_key="api-key",
        doubao_tts_voices=[HostSpeechVoiceConfig(voiceType="voice-a", label="音色 A")],
        doubao_tts_default_voice_type="voice-a",
    )

    assert settings.doubao_tts_api_key is not None
    assert settings.doubao_tts_api_key.get_secret_value() == "api-key"
    assert settings.doubao_tts_resource_id == "seed-tts-2.0"


def test_voice_allowlist_accepts_documented_camel_case_shape() -> None:
    voice = HostSpeechVoiceConfig.model_validate({"voiceType": "voice-a", "label": "音色 A"})
    assert voice.voice_type == "voice-a"


def test_doubao_new_console_auth_only_sends_api_key() -> None:
    headers = _build_doubao_headers(
        api_key="api-key",
        resource_id="seed-tts-2.0",
        request_id="request-id",
    )

    assert headers["X-Api-Key"] == "api-key"
    assert "X-Api-App-Key" not in headers
    assert "X-Api-Access-Key" not in headers


def test_v3_audio_frame_parser_reads_event_and_audio() -> None:
    session_id = b"session"
    audio = b"mp3-frame"
    packet = (
        b"\x11\xb4\x10\x00"
        + struct.pack(">i", 352)
        + struct.pack(">I", len(session_id))
        + session_id
        + struct.pack(">I", len(audio))
        + audio
    )
    frame = parse_server_frame(packet)
    assert frame.event == 352
    assert frame.audio == audio


async def test_authoritative_manifest_and_mp3_require_both_matching_identities(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    account_token = await register(client, account="speech-host")
    room = await create_room(client, token=account_token)
    event = Event(
        room_id=room["roomId"],
        event_type="narration.push",
        correlation_id="narration-1",
        visibility="public",
        payload={"messageId": "narration-1", "text": "门缓缓打开。"},
    )
    private_event = Event(
        room_id=room["roomId"],
        player_id=room["playerId"],
        event_type="narration.push",
        correlation_id="private-narration",
        visibility="player_scoped",
        payload={"messageId": "private-narration", "text": "只有房主能听见。"},
    )
    db_session.add_all([event, private_event])
    await db_session.commit()

    previous = app.state.host_speech
    # 不读取开发者本机 .env，避免真实豆包音色白名单污染 Fake Provider 集成测试。
    app.state.host_speech = build_host_speech_service(
        Settings(_env_file=None, host_speech_provider="fake")  # ty: ignore[unknown-argument]
    )
    headers = _combined_headers(account_token, room["reconnectToken"])
    try:
        settings_response = await client.get(
            f"/api/v1/rooms/{room['roomId']}/host-speech", headers=headers
        )
        assert settings_response.status_code == 200
        assert settings_response.json()["data"]["available"] is True

        updated = await client.patch(
            f"/api/v1/rooms/{room['roomId']}/host-speech",
            headers=headers,
            json={"voiceType": "fake-narrator"},
        )
        assert updated.status_code == 200
        assert updated.json()["data"]["voiceType"] == "fake-narrator"

        manifest = await client.get(
            f"/api/v1/rooms/{room['roomId']}/narrations/narration-1/speech",
            headers=headers,
        )
        assert manifest.status_code == 200
        assert (
            "".join(item["text"] for item in manifest.json()["data"]["sentences"]) == "门缓缓打开。"
        )

        audio = await client.get(
            f"/api/v1/rooms/{room['roomId']}/narrations/narration-1/speech/sentences/0",
            headers=headers,
        )
        assert audio.status_code == 200
        assert audio.headers["content-type"].startswith("audio/mpeg")
        assert audio.headers["cache-control"] == "no-store"

        other_account = await register(client, account="speech-other")
        mismatch = await client.get(
            f"/api/v1/rooms/{room['roomId']}/narrations/narration-1/speech",
            headers=_combined_headers(other_account, room["reconnectToken"]),
        )
        assert mismatch.status_code == 403

        guest = await join_room(client, room["roomCode"], other_account)
        hidden = await client.get(
            f"/api/v1/rooms/{room['roomId']}/narrations/private-narration/speech",
            headers=_combined_headers(other_account, guest["reconnectToken"]),
        )
        assert hidden.status_code == 404
    finally:
        app.state.host_speech = previous
