"""AI 主持人语音 Provider，以及豆包 V3 单向流式二进制协议。"""

from __future__ import annotations

import asyncio
import json
import struct
import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx
import structlog
from websockets.asyncio.client import connect

from app.adapters.structured_http import model_http_timeout

logger = structlog.get_logger()

DOUBAO_TTS_ENDPOINT = "wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream"
DOUBAO_LIST_SPEAKERS_ENDPOINT = (
    "https://open.volcengineapi.com/?Action=ListSpeakers&Version=2025-05-20"
)

_FULL_CLIENT_NO_EVENT = b"\x11\x10\x10\x00"
_FULL_CLIENT_WITH_EVENT = b"\x11\x14\x10\x00"
_MSG_FULL_SERVER = 0x94
_MSG_AUDIO_ONLY = 0xB4
_MSG_ERROR = 0xF0
_EVENT_FINISH_CONNECTION = 2
_EVENT_SESSION_FINISHED = 152
_EVENT_SESSION_FAILED = 153
_EVENT_TTS_RESPONSE = 352


class HostSpeechProviderError(Exception):
    """上游合成失败；message 永远是可公开的稳定类别。"""


class HostSpeechProviderTimeout(HostSpeechProviderError):
    pass


class HostSpeechProviderUnavailable(HostSpeechProviderError):
    pass


@dataclass(frozen=True, slots=True)
class HostSpeechRequest:
    text: str
    voice_type: str


@dataclass(frozen=True, slots=True)
class HostSpeechResult:
    audio: bytes
    content_type: str = "audio/mpeg"


@dataclass(frozen=True, slots=True)
class HostSpeechCatalogItem:
    """豆包资源包返回的可用音色；只保留稳定 ID 和公开名称。"""

    voice_type: str
    label: str


class HostSpeechProvider(Protocol):
    name: str
    version: str
    available: bool

    async def synthesize(self, request: HostSpeechRequest) -> HostSpeechResult: ...


def _build_doubao_headers(*, api_key: str, resource_id: str, request_id: str) -> dict[str, str]:
    # 新版豆包语音控制台只签发一个 API Key；不要再同时携带旧版
    # App/Access 请求头，否则会让部署配置的凭证语义变得不确定。
    return {
        "X-Api-Key": api_key,
        "X-Api-Resource-Id": resource_id,
        "X-Api-Connect-Id": request_id,
        "X-Control-Require-Usage-Tokens-Return": "*",
    }


class DisabledHostSpeechProvider:
    name = "disabled"
    version = "disabled-v1"
    available = False

    async def synthesize(self, request: HostSpeechRequest) -> HostSpeechResult:
        del request
        raise HostSpeechProviderUnavailable("主持人语音服务未配置")


class FakeHostSpeechProvider:
    """离线确定性 Provider；返回数帧静音 MP3，CI 不访问第三方网络。"""

    name = "fake"
    version = "fake-v1"
    available = True

    # MPEG-1 Layer III 128 kbps/44.1 kHz 帧。测试只关心稳定、非空的浏览器音频响应。
    _AUDIO = (b"\xff\xfb\x90\x64" + bytes(413)) * 4

    async def synthesize(self, request: HostSpeechRequest) -> HostSpeechResult:
        del request
        return HostSpeechResult(audio=self._AUDIO)


@dataclass(frozen=True, slots=True)
class _ServerFrame:
    message_type: int
    event: int
    audio: bytes = b""
    payload: object | None = None


def build_send_text_frame(payload: dict) -> bytes:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    return _FULL_CLIENT_NO_EVENT + struct.pack(">I", len(encoded)) + encoded


def build_finish_connection_frame() -> bytes:
    payload = b"{}"
    return (
        _FULL_CLIENT_WITH_EVENT
        + struct.pack(">i", _EVENT_FINISH_CONNECTION)
        + struct.pack(">I", len(payload))
        + payload
    )


def _read_length_prefixed(data: bytes, offset: int) -> tuple[bytes, int]:
    if offset + 4 > len(data):
        raise HostSpeechProviderError("豆包返回了不完整的协议帧")
    size = struct.unpack_from(">I", data, offset)[0]
    offset += 4
    if offset + size > len(data):
        raise HostSpeechProviderError("豆包返回了不完整的协议载荷")
    return data[offset : offset + size], offset + size


def _decode_json_or_text(payload: bytes) -> object | None:
    if not payload:
        return None
    text = payload.decode("utf-8", errors="replace")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def parse_server_frame(data: bytes) -> _ServerFrame:
    if len(data) < 4:
        raise HostSpeechProviderError("豆包返回了过短的协议帧")
    header_size = (data[0] & 0x0F) * 4
    if header_size < 4 or header_size > len(data):
        raise HostSpeechProviderError("豆包返回了非法协议头")
    message_type = data[1]
    offset = header_size
    if message_type == _MSG_ERROR:
        if offset + 4 > len(data):
            raise HostSpeechProviderError("豆包返回了不完整的错误帧")
        code = struct.unpack_from(">i", data, offset)[0]
        return _ServerFrame(message_type=message_type, event=code)
    if offset + 4 > len(data):
        raise HostSpeechProviderError("豆包返回了缺少事件号的协议帧")
    event = struct.unpack_from(">i", data, offset)[0]
    offset += 4
    # ConnectionFinished(52) 后是 connection id；其余响应均是 session id。
    _identity, offset = _read_length_prefixed(data, offset)
    if message_type == _MSG_AUDIO_ONLY:
        audio, _ = _read_length_prefixed(data, offset)
        return _ServerFrame(message_type=message_type, event=event, audio=audio)
    payload = None
    if message_type == _MSG_FULL_SERVER and offset < len(data):
        raw_payload, _ = _read_length_prefixed(data, offset)
        payload = _decode_json_or_text(raw_payload)
    return _ServerFrame(message_type=message_type, event=event, payload=payload)


class DoubaoHostSpeechProvider:
    name = "doubao"
    version = "doubao-v3-unidirectional-mp3-24k-v1"
    available = True

    def __init__(
        self,
        *,
        api_key: str,
        resource_id: str,
        timeout_seconds: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self._resource_id = resource_id
        self._timeout_seconds = timeout_seconds
        self._transport = transport

    async def list_speakers(self, resource_id: str) -> tuple[HostSpeechCatalogItem, ...]:
        """按当前 ResourceID 读取豆包可用音色，失败交给服务层安全降级。"""

        payload = {
            "ResourceIDs": [resource_id],
            "Page": 1,
            "Limit": "1000",
        }
        headers = {
            "X-Api-Key": self._api_key,
            "X-Api-Resource-Id": resource_id,
            "Content-Type": "application/json",
        }
        async with httpx.AsyncClient(
            # `_timeout_seconds` 就是这一次请求的预算，直接交给 model_http_timeout
            # 即可——不同于 DashScope 那两处，那里的预算还要覆盖轮询，所以先 min 再包。
            timeout=model_http_timeout(self._timeout_seconds),
            transport=self._transport,
        ) as client:
            response = await client.post(
                DOUBAO_LIST_SPEAKERS_ENDPOINT,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        result = body.get("Result") if isinstance(body, dict) else None
        speakers = result.get("Speakers") if isinstance(result, dict) else None
        if not isinstance(speakers, list):
            raise HostSpeechProviderError("豆包音色列表响应格式无效")
        items: dict[str, HostSpeechCatalogItem] = {}
        for speaker in speakers:
            if not isinstance(speaker, dict):
                continue
            voice_type = speaker.get("VoiceType")
            label = speaker.get("Name") or voice_type
            if isinstance(voice_type, str) and voice_type.startswith("zh_"):
                # 上游偶尔会在分页或资源聚合结果中重复音色；首个公开名称
                # 足够稳定，最终按 voice_type 排序保证配置和测试可复现。
                items.setdefault(
                    voice_type,
                    HostSpeechCatalogItem(
                        voice_type=voice_type,
                        label=label if isinstance(label, str) else voice_type,
                    ),
                )
        return tuple(items[key] for key in sorted(items))

    async def synthesize(self, request: HostSpeechRequest) -> HostSpeechResult:
        request_id = str(uuid.uuid4())
        headers = _build_doubao_headers(
            api_key=self._api_key,
            resource_id=self._resource_id,
            request_id=request_id,
        )
        payload = {
            # uid 只用于上游链路追踪；新版鉴权不再有 App ID，因此复用
            # 本次请求的唯一 ID，不传玩家账号或其他业务标识。
            "user": {"uid": request_id},
            "req_params": {
                "speaker": request.voice_type,
                "audio_params": {"format": "mp3", "sample_rate": 24000},
                "text": request.text,
            },
        }
        audio = bytearray()
        started = asyncio.get_running_loop().time()
        try:
            async with asyncio.timeout(self._timeout_seconds):
                async with connect(
                    DOUBAO_TTS_ENDPOINT,
                    additional_headers=headers,
                    max_size=8 * 1024 * 1024,
                ) as websocket:
                    await websocket.send(build_send_text_frame(payload))
                    finished = False
                    async for message in websocket:
                        if not isinstance(message, bytes):
                            raise HostSpeechProviderError("豆包返回了非二进制协议帧")
                        frame = parse_server_frame(message)
                        if frame.message_type == _MSG_ERROR or frame.event == _EVENT_SESSION_FAILED:
                            raise HostSpeechProviderError("豆包拒绝了语音合成请求")
                        if frame.event == _EVENT_TTS_RESPONSE and frame.audio:
                            audio.extend(frame.audio)
                        if frame.event == _EVENT_SESSION_FINISHED:
                            finished = True
                            await websocket.send(build_finish_connection_frame())
                            break
                    if not finished:
                        raise HostSpeechProviderError("豆包语音连接提前结束")
        except TimeoutError as exc:
            logger.warning("host_speech_timeout", request_id=request_id)
            raise HostSpeechProviderTimeout("豆包语音合成超时") from exc
        except HostSpeechProviderError:
            logger.warning("host_speech_provider_failed", request_id=request_id)
            raise
        except Exception as exc:
            logger.warning(
                "host_speech_transport_failed",
                request_id=request_id,
                error_type=type(exc).__name__,
            )
            raise HostSpeechProviderError("豆包语音服务连接失败") from exc
        if not audio:
            raise HostSpeechProviderError("豆包未返回音频数据")
        logger.info(
            "host_speech_synthesized",
            request_id=request_id,
            elapsed_ms=round((asyncio.get_running_loop().time() - started) * 1000),
            audio_bytes=len(audio),
        )
        return HostSpeechResult(audio=bytes(audio))
