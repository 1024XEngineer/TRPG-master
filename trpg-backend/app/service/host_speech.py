"""AI 主持人语音业务层：权威消息读取、分句、限流、缓存与请求合并。"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass

from collaboration_framework.contracts import ModuleContentV3
from collaboration_framework.host.application import split_narration_chunks
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.host_speech import (
    HostSpeechProvider,
    HostSpeechRequest,
    HostSpeechResult,
)
from app.core.config import HostSpeechVoiceConfig, Settings, secret_value
from app.models.content import Scenario
from app.models.engine import ModuleVersion
from app.models.event import Event, EventAudience
from app.models.room import Player, Room


class HostSpeechError(Exception):
    pass


class HostSpeechUnavailableError(HostSpeechError):
    pass


class HostSpeechNotFoundError(HostSpeechError):
    pass


class HostSpeechForbiddenError(HostSpeechError):
    pass


class HostSpeechInvalidRequestError(HostSpeechError):
    pass


class HostSpeechRateLimitedError(HostSpeechError):
    pass


@dataclass(frozen=True, slots=True)
class CachedAudio:
    result: HostSpeechResult
    expires_at: float


def _split_utf8(text: str, max_bytes: int) -> tuple[str, ...]:
    if len(text.encode()) <= max_bytes:
        return (text,)
    chunks: list[str] = []
    start = 0
    used = 0
    for index, character in enumerate(text):
        size = len(character.encode())
        if used and used + size > max_bytes:
            chunks.append(text[start:index])
            start = index
            used = 0
        used += size
    if start < len(text):
        chunks.append(text[start:])
    return tuple(chunks)


def split_narration_for_speech(text: str, max_bytes: int) -> tuple[str, ...]:
    sentences = tuple(
        part
        for chunk in split_narration_chunks(text)
        for part in _split_utf8(chunk, max_bytes)
        if part
    )
    if "".join(sentences) != text:
        raise HostSpeechInvalidRequestError("主持人叙事无法稳定分句")
    return sentences


class _WindowRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str, limit: int, now: float) -> None:
        events = self._events[key]
        cutoff = now - 60
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= limit:
            raise HostSpeechRateLimitedError("主持人语音请求过于频繁，请稍后再试")
        events.append(now)


class HostSpeechService:
    def __init__(
        self,
        provider: HostSpeechProvider,
        *,
        voices: list[HostSpeechVoiceConfig],
        default_voice_type: str | None,
        max_sentence_bytes: int,
        cache_ttl_seconds: int,
        cache_max_bytes: int,
        player_requests_per_minute: int,
        room_misses_per_minute: int,
        max_concurrency: int,
        resource_id: str = "",
    ) -> None:
        self.provider = provider
        self.voices = voices
        self.default_voice_type = default_voice_type
        self.max_sentence_bytes = max_sentence_bytes
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache_max_bytes = cache_max_bytes
        self._cache: OrderedDict[str, CachedAudio] = OrderedDict()
        self._cache_bytes = 0
        self._inflight: dict[str, asyncio.Future[HostSpeechResult]] = {}
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._player_limiter = _WindowRateLimiter()
        self._room_limiter = _WindowRateLimiter()
        self._player_limit = player_requests_per_minute
        self._room_limit = room_misses_per_minute
        # 资源包属于部署配置；NPC profile 只有与此值一致时才允许使用。
        self.resource_id = resource_id

    @property
    def available(self) -> bool:
        return self.provider.available and bool(self.voices) and self.default_voice_type is not None

    @property
    def allowed_voice_types(self) -> set[str]:
        return {voice.voice_type for voice in self.voices}

    def effective_voice_type(self, stored: str | None) -> str | None:
        return stored if stored in self.allowed_voice_types else self.default_voice_type

    def sentences(self, text: str) -> tuple[str, ...]:
        return split_narration_for_speech(text, self.max_sentence_bytes)

    def _cache_key(self, text: str, voice_type: str) -> str:
        digest = hashlib.sha256(text.encode()).hexdigest()
        return f"{self.provider.version}:{self.resource_id}:mp3:{voice_type}:{digest}"

    def _evict_expired(self, now: float) -> None:
        expired = [key for key, entry in self._cache.items() if entry.expires_at <= now]
        for key in expired:
            entry = self._cache.pop(key)
            self._cache_bytes -= len(entry.result.audio)

    def _store(self, key: str, result: HostSpeechResult, now: float) -> None:
        if self._cache_ttl_seconds <= 0 or self._cache_max_bytes <= 0:
            return
        if len(result.audio) > self._cache_max_bytes:
            return
        previous = self._cache.pop(key, None)
        if previous is not None:
            self._cache_bytes -= len(previous.result.audio)
        self._cache[key] = CachedAudio(result, now + self._cache_ttl_seconds)
        self._cache_bytes += len(result.audio)
        while self._cache and self._cache_bytes > self._cache_max_bytes:
            _old_key, old = self._cache.popitem(last=False)
            self._cache_bytes -= len(old.result.audio)

    async def synthesize(
        self,
        *,
        room_id: str,
        player_id: str,
        text: str,
        voice_type: str,
    ) -> HostSpeechResult:
        if not self.available:
            raise HostSpeechUnavailableError("主持人语音服务未配置")
        if voice_type not in self.allowed_voice_types:
            raise HostSpeechInvalidRequestError("主持人音色不可用")
        now = time.monotonic()
        self._player_limiter.check(player_id, self._player_limit, now)
        key = self._cache_key(text, voice_type)
        owner = False
        async with self._lock:
            self._evict_expired(now)
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                return cached.result
            future = self._inflight.get(key)
            if future is None:
                # 房间 Provider 限额只统计真正的缓存缺失。相同文本的并发请求共享
                # 一个 Future，既避免重复计费，也避免把多名玩家同时播放算成多次。
                self._room_limiter.check(room_id, self._room_limit, now)
                future = asyncio.get_running_loop().create_future()
                self._inflight[key] = future
                owner = True
        if not owner:
            return await asyncio.shield(future)
        try:
            async with self._semaphore:
                result = await self.provider.synthesize(
                    HostSpeechRequest(text=text, voice_type=voice_type)
                )
            async with self._lock:
                self._store(key, result, time.monotonic())
            future.set_result(result)
            return result
        except BaseException as exc:
            if not future.done():
                future.set_exception(exc)
                # Owner 直接重新抛出；取一次 exception 避免没有 waiter 时产生警告。
                future.exception()
            raise
        finally:
            async with self._lock:
                self._inflight.pop(key, None)


def build_host_speech_service(settings: Settings) -> HostSpeechService:
    from app.adapters.host_speech import (
        DisabledHostSpeechProvider,
        DoubaoHostSpeechProvider,
        FakeHostSpeechProvider,
    )

    voices = settings.doubao_tts_voices
    default_voice = settings.doubao_tts_default_voice_type
    if settings.host_speech_provider == "fake" and not voices:
        voices = [HostSpeechVoiceConfig(voiceType="fake-narrator", label="测试主持人")]
        default_voice = "fake-narrator"
    if settings.host_speech_provider == "doubao":
        assert settings.doubao_tts_api_key is not None
        provider: HostSpeechProvider = DoubaoHostSpeechProvider(
            api_key=secret_value(settings.doubao_tts_api_key),
            resource_id=settings.doubao_tts_resource_id or "",
            timeout_seconds=settings.doubao_tts_timeout_seconds,
        )
    elif settings.host_speech_provider == "fake":
        provider = FakeHostSpeechProvider()
    else:
        provider = DisabledHostSpeechProvider()
    return HostSpeechService(
        provider,
        voices=voices,
        default_voice_type=default_voice,
        max_sentence_bytes=settings.host_speech_max_sentence_bytes,
        cache_ttl_seconds=settings.host_speech_cache_ttl_seconds,
        cache_max_bytes=settings.host_speech_cache_max_bytes,
        player_requests_per_minute=settings.host_speech_player_requests_per_minute,
        room_misses_per_minute=settings.host_speech_room_misses_per_minute,
        max_concurrency=settings.host_speech_max_concurrency,
        resource_id=settings.doubao_tts_resource_id,
    )


async def require_account_room_member(
    db: AsyncSession,
    room_id: str,
    reconnect_token: str | None,
    user_id: str,
) -> Player:
    # Authorization 证明账号是谁，reconnect token 证明房内玩家是谁；只校验其中
    # 一个会允许拿到别人重连凭证的账号越权，必须交叉验证两者指向同一行 Player。
    from app.service.room import require_room_member

    player = await require_room_member(db, room_id, reconnect_token)
    if player.user_id != user_id:
        raise HostSpeechForbiddenError("登录账号与房间身份不匹配")
    return player


async def find_visible_narration(
    db: AsyncSession,
    *,
    room_id: str,
    message_id: str,
    player_id: str,
) -> Event:
    event = await db.scalar(
        select(Event).where(
            Event.room_id == room_id,
            Event.event_type == "narration.push",
            Event.correlation_id == message_id,
            or_(
                Event.visibility == "public",
                and_(Event.visibility == "player_scoped", Event.player_id == player_id),
            ),
        )
    )
    if event is None:
        raise HostSpeechNotFoundError("主持人消息不存在")
    if not isinstance(event.payload.get("text"), str) or not event.payload["text"]:
        raise HostSpeechInvalidRequestError("主持人消息没有可朗读文本")
    return event


async def find_visible_dialogue(
    db: AsyncSession,
    *,
    room_id: str,
    message_id: str,
    player_id: str,
) -> Event:
    """按冻结 audience 查找 NPC 对话，避免后来进场的玩家读取历史语音。"""

    event = await db.scalar(
        select(Event)
        .join(EventAudience, EventAudience.event_id == Event.id)
        .where(
            Event.room_id == room_id,
            Event.event_type == "dialogue.npc",
            or_(Event.id == message_id, Event.correlation_id == message_id),
            EventAudience.player_id == player_id,
        )
    )
    if event is None:
        raise HostSpeechNotFoundError("NPC 对话不存在或当前玩家无权读取")
    if not isinstance(event.payload.get("text"), str) or not event.payload["text"]:
        raise HostSpeechInvalidRequestError("NPC 对话没有可朗读文本")
    return event


async def get_npc_voice(
    db: AsyncSession,
    *,
    room_id: str,
    event: Event,
    service: HostSpeechService,
) -> str:
    """从不可变 ModuleContent 按 speaker_id 解析 NPC 音色；失败时安全回退。"""

    fallback = service.default_voice_type
    room = await db.get(Room, room_id)
    if room is None or room.scenario_id is None:
        if fallback is None:
            raise HostSpeechUnavailableError("主持人语音服务未配置")
        return fallback
    scenario = await db.get(Scenario, room.scenario_id)
    version = room.module_version or (scenario.version if scenario else None)
    if scenario is None or version is None:
        if fallback is None:
            raise HostSpeechUnavailableError("主持人语音服务未配置")
        return fallback
    module_version = await db.get(ModuleVersion, (scenario.module_id, version))
    # 事件规范使用 camelCase；兼容早期测试/历史行的 snake_case 载荷。
    speaker_id = event.payload.get("speakerId") or event.payload.get("speaker_id") or event.actor_id
    if not isinstance(speaker_id, str) or not speaker_id.strip() or module_version is None:
        raise HostSpeechNotFoundError("NPC 音色对应的实体不存在")
    try:
        content = ModuleContentV3.model_validate(module_version.content_json)
    except (TypeError, ValueError) as exc:
        raise HostSpeechUnavailableError("模组音色配置无法读取") from exc
    entity = next(
        (item for item in content.entities if item.kind == "npc" and item.id == speaker_id),
        None,
    )
    if entity is None:
        raise HostSpeechNotFoundError("NPC 音色对应的实体不存在")
    profile = entity.voice
    if (
        profile is not None
        and profile.provider == service.provider.name
        and profile.resource_id == service.resource_id
        and profile.voice_type in service.allowed_voice_types
    ):
        return profile.voice_type
    # 合法 NPC 但 profile 与当前部署不匹配时安全回退，不影响文字对话。
    if fallback is None or fallback not in service.allowed_voice_types:
        raise HostSpeechUnavailableError("NPC 音色不可用，但文字对话仍可继续")
    return fallback


async def get_room_voice(db: AsyncSession, room_id: str, service: HostSpeechService) -> str:
    room = await db.get(Room, room_id)
    if room is None:
        raise HostSpeechNotFoundError("房间不存在")
    voice_type = service.effective_voice_type(room.host_speech_voice_type)
    if voice_type is None:
        raise HostSpeechUnavailableError("主持人语音服务未配置")
    return voice_type
