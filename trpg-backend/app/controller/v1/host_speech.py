"""房间 AI 主持人语音设置、权威分句清单和 MP3 音频。"""

from typing import NoReturn

from fastapi import APIRouter, Depends, Header, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.adapters.host_speech import HostSpeechProviderError, HostSpeechProviderTimeout
from app.controller.dependencies import get_current_user
from app.core.db import get_db
from app.core.errors import AppException, ErrorCode
from app.dto.common import ApiResponse
from app.dto.host_speech import (
    HostSpeechManifestRead,
    HostSpeechSentenceRead,
    HostSpeechSettingsRead,
    HostSpeechSettingsUpdate,
    HostSpeechVoiceRead,
)
from app.models.room import Player, Room
from app.models.user import User
from app.service.host_speech import (
    HostSpeechForbiddenError,
    HostSpeechInvalidRequestError,
    HostSpeechNotFoundError,
    HostSpeechRateLimitedError,
    HostSpeechService,
    HostSpeechUnavailableError,
    find_visible_dialogue,
    find_visible_narration,
    get_npc_voice,
    get_room_voice,
    require_account_room_member,
)
from app.service.ws_events import broadcast_host_speech_settings

router = APIRouter(prefix="/rooms", tags=["host-speech"])


def _service(request: Request) -> HostSpeechService:
    return request.app.state.host_speech


def _raise_public_error(exc: Exception) -> NoReturn:
    if isinstance(exc, HostSpeechForbiddenError):
        raise AppException(ErrorCode.FORBIDDEN, str(exc), status.HTTP_403_FORBIDDEN) from exc
    if isinstance(exc, HostSpeechNotFoundError):
        raise AppException(ErrorCode.NOT_FOUND, str(exc), status.HTTP_404_NOT_FOUND) from exc
    if isinstance(exc, HostSpeechInvalidRequestError):
        raise AppException(
            ErrorCode.VALIDATION_ERROR, str(exc), status.HTTP_422_UNPROCESSABLE_ENTITY
        ) from exc
    if isinstance(exc, HostSpeechUnavailableError):
        raise AppException(
            ErrorCode.HOST_SPEECH_UNAVAILABLE,
            str(exc),
            status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    if isinstance(exc, HostSpeechRateLimitedError):
        raise AppException(
            ErrorCode.RATE_LIMITED, str(exc), status.HTTP_429_TOO_MANY_REQUESTS
        ) from exc
    if isinstance(exc, HostSpeechProviderTimeout):
        raise AppException(
            ErrorCode.HOST_SPEECH_TIMEOUT, str(exc), status.HTTP_504_GATEWAY_TIMEOUT
        ) from exc
    if isinstance(exc, HostSpeechProviderError):
        raise AppException(
            ErrorCode.HOST_SPEECH_FAILED,
            "主持人语音合成失败，请稍后手动重播",
            status.HTTP_502_BAD_GATEWAY,
        ) from exc
    raise exc


async def _member(
    db: AsyncSession,
    room_id: str,
    reconnect_token: str | None,
    user: User,
) -> Player:
    try:
        return await require_account_room_member(db, room_id, reconnect_token, user.id)
    except Exception as exc:
        _raise_public_error(exc)


def _settings(room: Room, service: HostSpeechService) -> HostSpeechSettingsRead:
    return HostSpeechSettingsRead(
        available=service.available,
        provider=service.provider.name,
        voice_type=service.effective_voice_type(room.host_speech_voice_type),
        voices=[
            HostSpeechVoiceRead(voice_type=voice.voice_type, label=voice.label)
            for voice in service.voices
        ],
    )


@router.get("/{room_id}/host-speech", response_model=ApiResponse[HostSpeechSettingsRead])
async def get_host_speech_settings(
    room_id: str,
    request: Request,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse[HostSpeechSettingsRead]:
    await _member(db, room_id, reconnect_token, user)
    room = await db.get(Room, room_id)
    if room is None:
        _raise_public_error(HostSpeechNotFoundError("房间不存在"))
    service = _service(request)
    await service.refresh_voice_catalog()
    return ApiResponse.ok(_settings(room, service))


@router.patch("/{room_id}/host-speech", response_model=ApiResponse[HostSpeechSettingsRead])
async def update_host_speech_settings(
    room_id: str,
    payload: HostSpeechSettingsUpdate,
    request: Request,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse[HostSpeechSettingsRead]:
    player = await _member(db, room_id, reconnect_token, user)
    room = await db.get(Room, room_id)
    if room is None:
        _raise_public_error(HostSpeechNotFoundError("房间不存在"))
    if player.id != room.host_player_id:
        _raise_public_error(HostSpeechForbiddenError("仅房主可以更换主持人音色"))
    service = _service(request)
    await service.refresh_voice_catalog()
    if payload.voice_type not in service.allowed_voice_types:
        _raise_public_error(HostSpeechInvalidRequestError("主持人音色不在允许列表中"))
    room.host_speech_voice_type = payload.voice_type
    await db.commit()
    await db.refresh(room)
    await broadcast_host_speech_settings(room_id, payload.voice_type)
    return ApiResponse.ok(_settings(room, service))


@router.get(
    "/{room_id}/narrations/{message_id}/speech",
    response_model=ApiResponse[HostSpeechManifestRead],
)
async def get_host_speech_manifest(
    room_id: str,
    message_id: str,
    request: Request,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse[HostSpeechManifestRead]:
    player = await _member(db, room_id, reconnect_token, user)
    try:
        event = await find_visible_narration(
            db, room_id=room_id, message_id=message_id, player_id=player.id
        )
        sentences = _service(request).sentences(event.payload["text"])
    except Exception as exc:
        _raise_public_error(exc)
    return ApiResponse.ok(
        HostSpeechManifestRead(
            message_id=message_id,
            sentences=[
                HostSpeechSentenceRead(index=index, text=text)
                for index, text in enumerate(sentences)
            ],
        )
    )


@router.get("/{room_id}/narrations/{message_id}/speech/sentences/{sentence_index}")
async def get_host_speech_sentence(
    room_id: str,
    message_id: str,
    sentence_index: int,
    request: Request,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    player = await _member(db, room_id, reconnect_token, user)
    service = _service(request)
    try:
        event = await find_visible_narration(
            db, room_id=room_id, message_id=message_id, player_id=player.id
        )
        sentences = service.sentences(event.payload["text"])
        if sentence_index < 0 or sentence_index >= len(sentences):
            raise HostSpeechNotFoundError("主持人语音分句不存在")
        voice_type = await get_room_voice(db, room_id, service)
        result = await service.synthesize(
            room_id=room_id,
            player_id=player.id,
            text=sentences[sentence_index],
            voice_type=voice_type,
        )
    except Exception as exc:
        _raise_public_error(exc)
    return Response(
        content=result.audio,
        media_type=result.content_type,
        headers={"Cache-Control": "no-store"},
    )


@router.get(
    "/{room_id}/dialogues/{message_id}/speech",
    response_model=ApiResponse[HostSpeechManifestRead],
)
async def get_npc_speech_manifest(
    room_id: str,
    message_id: str,
    request: Request,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ApiResponse[HostSpeechManifestRead]:
    """读取有 audience 权限的 NPC 对话分句清单。"""

    player = await _member(db, room_id, reconnect_token, user)
    try:
        event = await find_visible_dialogue(
            db, room_id=room_id, message_id=message_id, player_id=player.id
        )
        sentences = _service(request).sentences(event.payload["text"])
    except Exception as exc:
        _raise_public_error(exc)
    return ApiResponse.ok(
        HostSpeechManifestRead(
            message_id=message_id,
            sentences=[
                HostSpeechSentenceRead(index=index, text=text)
                for index, text in enumerate(sentences)
            ],
        )
    )


@router.get("/{room_id}/dialogues/{message_id}/speech/sentences/{sentence_index}")
async def get_npc_speech_sentence(
    room_id: str,
    message_id: str,
    sentence_index: int,
    request: Request,
    reconnect_token: str | None = Header(default=None, alias="X-Reconnect-Token"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """按对话 speaker_id 解析专属音色并返回一条 MP3；失败不修改事件。"""

    player = await _member(db, room_id, reconnect_token, user)
    service = _service(request)
    try:
        event = await find_visible_dialogue(
            db, room_id=room_id, message_id=message_id, player_id=player.id
        )
        sentences = service.sentences(event.payload["text"])
        if sentence_index < 0 or sentence_index >= len(sentences):
            raise HostSpeechNotFoundError("NPC 语音分句不存在")
        voice_type = await get_npc_voice(db, room_id=room_id, event=event, service=service)
        result = await service.synthesize(
            room_id=room_id,
            player_id=player.id,
            text=sentences[sentence_index],
            voice_type=voice_type,
        )
    except Exception as exc:
        _raise_public_error(exc)
    return Response(
        content=result.audio,
        media_type=result.content_type,
        headers={"Cache-Control": "no-store"},
    )
