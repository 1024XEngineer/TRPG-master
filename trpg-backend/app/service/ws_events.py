"""跨 HTTP / WebSocket 控制器复用的房间状态推送。"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.host_speech import HostSpeechSettingsUpdatedPayload
from app.dto.ws import RoomStatePayload, ServerEnvelope
from app.service import room as room_service
from app.service.ws_manager import manager


async def broadcast_room_state(db: AsyncSession, room_id: str) -> None:
    room = await room_service.find_room_by_id(db, room_id)
    preview = await room_service.get_room_preview(db, room.room_code)
    if preview is None:
        return
    payload = RoomStatePayload(
        room_id=room_id,
        phase=preview.phase,
        players=preview.players,
    )
    envelope = ServerEnvelope(type="room.state", payload=payload.model_dump(by_alias=True))
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))


async def broadcast_host_speech_settings(room_id: str, voice_type: str | None) -> None:
    payload = HostSpeechSettingsUpdatedPayload(voice_type=voice_type)
    envelope = ServerEnvelope(
        type="host_speech.settings_updated",
        payload=payload.model_dump(by_alias=True),
    )
    await manager.broadcast(room_id, envelope.model_dump(by_alias=True))


__all__ = ["broadcast_host_speech_settings", "broadcast_room_state"]
