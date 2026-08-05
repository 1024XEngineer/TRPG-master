"""AI 主持人语音 REST / WebSocket 契约。"""

from pydantic import Field

from app.dto.common import CamelModel


class HostSpeechVoiceRead(CamelModel):
    voice_type: str
    label: str


class HostSpeechSettingsRead(CamelModel):
    available: bool
    provider: str
    voice_type: str | None
    voices: list[HostSpeechVoiceRead]
    auto_emotion: bool = True


class HostSpeechSettingsUpdate(CamelModel):
    voice_type: str = Field(min_length=1, max_length=200)


class HostSpeechSentenceRead(CamelModel):
    index: int = Field(ge=0)
    text: str


class HostSpeechManifestRead(CamelModel):
    message_id: str
    sentences: list[HostSpeechSentenceRead]


class HostSpeechSettingsUpdatedPayload(CamelModel):
    voice_type: str | None
