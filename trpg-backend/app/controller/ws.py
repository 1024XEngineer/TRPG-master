"""房间 WebSocket：身份绑定、权威回合、检定确认与玩家安全状态推送。"""

from __future__ import annotations

import uuid

import structlog
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import async_session_factory
from app.dto.ws import (
    ActionSubmitPayload,
    CheckRequestPayload,
    CheckResultPayload,
    CheckRollPayload,
    ClientEnvelope,
    ClueGrantedPayload,
    ErrorPayload,
    GameEndedPayload,
    GameStartPayload,
    GameViewPayload,
    NarrationPushPayload,
    PlayerReadyPayload,
    RoomJoinPayload,
    RoomRejoinPayload,
    SanCheckRequestPayload,
    SanCheckResultPayload,
    SanCheckRollPayload,
    ServerEnvelope,
    SessionBoundPayload,
)
from app.models.event import Event
from app.models.replay import RoomSession
from app.models.room import Character
from app.runtime.bootstrap import get_turn_orchestrator
from app.runtime.contracts import PlayerInput, RuntimeEvent, TurnResult
from app.runtime.engine import RuntimeConflictError, StaleRevisionError
from app.service import auth as auth_service
from app.service import room as room_service
from app.service.ws_manager import manager

router = APIRouter()
logger = structlog.get_logger()

_UNAUTHORIZED_CLOSE_CODE = 4401
_NOT_FOUND_CLOSE_CODE = 4404


def _envelope(
    event_type: str,
    payload,
    *,
    event_id: str | None = None,
    sequence: int | None = None,
) -> dict:
    payload_data = (
        payload.model_dump(by_alias=True) if hasattr(payload, "model_dump") else payload
    )
    return ServerEnvelope(
        type=event_type,
        payload=payload_data,
        event_id=event_id or str(uuid.uuid4()),
        sequence=sequence,
    ).model_dump(by_alias=True)


async def _send_error(websocket: WebSocket, code: str, message: str) -> None:
    await websocket.send_json(_envelope("error", ErrorPayload(code=code, message=message)))


async def _handle_room_join(
    db: AsyncSession,
    websocket: WebSocket,
    room_id: str,
    player_id: str | None,
    reconnect_token: str,
) -> bool:
    player = await room_service.get_player(db, player_id) if player_id else None
    if player is None or player.room_id != room_id or player.reconnect_token != reconnect_token:
        await websocket.close(code=_NOT_FOUND_CLOSE_CODE)
        return False
    assert player_id is not None
    manager.add(room_id, websocket)
    await room_service.set_player_connected(db, player_id, True)
    await websocket.send_json(
        _envelope(
            "session.bound",
            SessionBoundPayload(room_id=room_id, player_id=player_id),
        )
    )
    return True


async def _runtime_identity(
    db: AsyncSession, room_id: str, player_id: str
) -> tuple[RoomSession, Character]:
    session = await get_turn_orchestrator().store.active_session(db, room_id)
    if session is None:
        raise RuntimeConflictError("房间没有进行中的游戏")
    character = await db.scalar(
        select(Character).where(
            Character.room_id == room_id,
            Character.player_id == player_id,
            Character.status == "complete",
        )
    )
    if character is None:
        raise RuntimeConflictError("当前玩家没有已完成的调查员")
    return session, character


async def _send_current_view(
    db: AsyncSession, websocket: WebSocket, room_id: str, player_id: str
) -> None:
    try:
        _, character = await _runtime_identity(db, room_id, player_id)
        view = await get_turn_orchestrator().current_view(
            db, room_id=room_id, actor_id=character.id
        )
    except (RuntimeConflictError, ValueError):
        return
    payload = GameViewPayload(**view.model_dump())
    await websocket.send_json(
        _envelope("game.view", payload, sequence=view.event_sequence)
    )


def _runtime_event_envelope(
    player_id: str,
    state_revision: int,
    event: RuntimeEvent,
    *,
    event_id: str | None = None,
    sequence: int | None = None,
) -> dict | None:
    payload = event.payload
    if event.event_type == "check.requested":
        model = CheckRequestPayload(
            player_id=player_id,
            check_request_id=payload["check_request_id"],
            checkpoint_id=payload["checkpoint_id"],
            skill=payload["skill_id"],
            target_value=payload["target_value"],
            difficulty=payload["difficulty"],
            reason=payload["reason"],
            state_revision=state_revision,
        )
        return _envelope(
            "check.request", model, event_id=event_id, sequence=sequence
        )
    elif event.event_type == "san.requested":
        model = SanCheckRequestPayload(
            player_id=player_id,
            check_request_id=payload["check_request_id"],
            sanity_event_id=payload["sanity_event_id"],
            current_san=payload["target_value"],
            reason=payload["reason"],
            state_revision=state_revision,
        )
        return _envelope(
            "san.check.request", model, event_id=event_id, sequence=sequence
        )
    elif event.event_type == "check.resolved":
        model = CheckResultPayload(
            player_id=player_id,
            check_request_id=payload["checkRequestId"],
            checkpoint_id=payload["checkpointId"],
            skill=payload["skillId"],
            roll_value=payload["rollValue"],
            target_value=payload["targetValue"],
            result=payload["grade"],
            state_revision=state_revision,
        )
        return _envelope(
            "check.result", model, event_id=event_id, sequence=sequence
        )
    elif event.event_type == "san.resolved":
        model = SanCheckResultPayload(
            player_id=player_id,
            check_request_id=payload["checkRequestId"],
            sanity_event_id=payload["sanityEventId"],
            roll_value=payload["rollValue"],
            san_loss=payload["sanLoss"],
            result="success" if payload["succeeded"] else "failure",
            current_san=payload["currentSan"],
            state_revision=state_revision,
        )
        return _envelope(
            "san.check.result", model, event_id=event_id, sequence=sequence
        )
    elif event.event_type == "clue.granted":
        model = ClueGrantedPayload(
            player_id=player_id,
            clue_id=payload["clueId"],
            clue_name=payload["name"],
            description=payload.get("description"),
        )
        return _envelope(
            "clue.granted", model, event_id=event_id, sequence=sequence
        )
    elif event.event_type == "game.ended":
        model = GameEndedPayload(
            reason=payload.get("summary"),
            ending_id=payload.get("endingId"),
            outcome=payload.get("outcome"),
            summary=payload.get("summary"),
            state_revision=state_revision,
        )
        return _envelope(
            "game.ended", model, event_id=event_id, sequence=sequence
        )
    return None


async def _broadcast_runtime_event(
    room_id: str,
    player_id: str,
    state_revision: int,
    event: RuntimeEvent,
) -> None:
    message = _runtime_event_envelope(player_id, state_revision, event)
    if message is not None:
        await manager.broadcast(room_id, message)


async def _replay_missed_events(
    db: AsyncSession,
    websocket: WebSocket,
    *,
    room_id: str,
    player_id: str,
    last_sequence: int,
) -> None:
    session = await get_turn_orchestrator().store.active_session(db, room_id)
    if session is None:
        return
    events = await db.scalars(
        select(Event)
        .where(
            Event.room_session_id == session.id,
            Event.sequence > last_sequence,
            or_(
                Event.visibility == "room",
                (Event.visibility == "player") & (Event.player_id == player_id),
            ),
        )
        .order_by(Event.sequence)
    )
    for event in events:
        if event.event_type == "narration.push":
            message = _envelope(
                "narration.push",
                NarrationPushPayload(
                    text=str(event.payload.get("text", "")),
                    request_id=event.request_id,
                    state_revision=event.state_revision,
                ),
                event_id=event.id,
                sequence=event.sequence,
            )
        else:
            message = _runtime_event_envelope(
                event.player_id or player_id,
                event.state_revision or 0,
                RuntimeEvent(
                    event_type=event.event_type,
                    payload=event.payload,
                    visibility="room",
                ),
                event_id=event.id,
                sequence=event.sequence,
            )
        if message is not None:
            await websocket.send_json(message)


async def _broadcast_turn(
    room_id: str,
    player_id: str,
    turn: TurnResult,
) -> None:
    for event in turn.action.events:
        if event.visibility != "keeper":
            await _broadcast_runtime_event(
                room_id,
                player_id,
                turn.action.state_revision,
                event,
            )
    narration = NarrationPushPayload(
        text=turn.narration.text,
        request_id=turn.action.request_id,
        state_revision=turn.action.state_revision,
    )
    await manager.broadcast(
        room_id,
        _envelope(
            "narration.push",
            narration,
            sequence=turn.view.event_sequence,
        ),
    )
    await manager.broadcast(
        room_id,
        _envelope(
            "game.view",
            GameViewPayload(**turn.view.model_dump()),
            sequence=turn.view.event_sequence,
        ),
    )


async def _handle_action(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
    payload: ActionSubmitPayload,
) -> None:
    session, character = await _runtime_identity(db, room_id, player_id)
    player_input = PlayerInput(
        request_id=payload.client_action_id,
        room_id=room_id,
        room_session_id=session.id,
        player_id=player_id,
        actor_id=character.id,
        source_revision=payload.source_revision,
        utterance=payload.utterance.strip(),
    )
    turn = await get_turn_orchestrator().run(db, player_input)
    await _broadcast_turn(room_id, player_id, turn)


async def _handle_roll(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
    client_action_id: str,
    check_request_id: str,
    source_revision: int,
) -> None:
    session, character = await _runtime_identity(db, room_id, player_id)
    player_input = PlayerInput(
        request_id=client_action_id,
        room_id=room_id,
        room_session_id=session.id,
        player_id=player_id,
        actor_id=character.id,
        source_revision=source_revision,
        utterance="确认掷骰",
    )
    turn = await get_turn_orchestrator().resolve_pending(
        db,
        player_input=player_input,
        check_request_id=check_request_id,
    )
    await _broadcast_turn(room_id, player_id, turn)


@router.websocket("/ws/{room_id}")
async def room_socket(
    websocket: WebSocket, room_id: str, token: str | None = None
) -> None:
    async with async_session_factory() as db:
        try:
            await auth_service.get_me(db, token)
        except auth_service.AuthenticationError:
            await websocket.close(code=_UNAUTHORIZED_CLOSE_CODE)
            return

    await websocket.accept()
    bound_player_id: str | None = None
    bound_reconnect_token: str | None = None

    try:
        while True:
            raw = await websocket.receive_json()
            try:
                client_envelope = ClientEnvelope.model_validate(raw)
            except ValidationError as exc:
                logger.warning("ws_invalid_message", error=str(exc))
                continue

            event_type = client_envelope.type
            raw_payload = client_envelope.payload
            async with async_session_factory() as db:
                try:
                    if event_type == "room.join":
                        payload = RoomJoinPayload.model_validate(raw_payload)
                        if await _handle_room_join(
                            db,
                            websocket,
                            room_id,
                            client_envelope.player_id,
                            payload.reconnect_token,
                        ):
                            bound_player_id = client_envelope.player_id
                            bound_reconnect_token = payload.reconnect_token
                            assert bound_player_id is not None
                            await _send_current_view(
                                db, websocket, room_id, bound_player_id
                            )
                        else:
                            return
                        continue

                    if bound_player_id is None:
                        continue

                    if event_type == "player.ready":
                        payload = PlayerReadyPayload.model_validate(raw_payload)
                        await room_service.set_player_ready(
                            db, bound_player_id, payload.ready
                        )
                    elif event_type == "game.start":
                        GameStartPayload.model_validate(raw_payload)
                        view = await room_service.begin_game(
                            db, room_id, bound_player_id
                        )
                        await manager.broadcast(
                            room_id,
                            _envelope(
                                "narration.push",
                                NarrationPushPayload(
                                    text=view.scene.player_description,
                                    state_revision=view.state_revision,
                                ),
                            ),
                        )
                        await manager.broadcast(
                            room_id,
                            _envelope(
                                "game.view",
                                GameViewPayload(**view.model_dump()),
                                sequence=view.event_sequence,
                            ),
                        )
                    elif event_type == "action.submit":
                        payload = ActionSubmitPayload.model_validate(raw_payload)
                        if payload.utterance.strip():
                            await _handle_action(
                                db,
                                room_id=room_id,
                                player_id=bound_player_id,
                                payload=payload,
                            )
                    elif event_type == "check.roll":
                        payload = CheckRollPayload.model_validate(raw_payload)
                        await _handle_roll(
                            db,
                            room_id=room_id,
                            player_id=bound_player_id,
                            client_action_id=payload.client_action_id,
                            check_request_id=payload.check_request_id,
                            source_revision=payload.source_revision,
                        )
                    elif event_type == "san.check.roll":
                        payload = SanCheckRollPayload.model_validate(raw_payload)
                        await _handle_roll(
                            db,
                            room_id=room_id,
                            player_id=bound_player_id,
                            client_action_id=payload.client_action_id,
                            check_request_id=payload.check_request_id,
                            source_revision=payload.source_revision,
                        )
                    elif event_type == "room.rejoin":
                        payload = RoomRejoinPayload.model_validate(raw_payload)
                        if payload.reconnect_token != bound_reconnect_token:
                            await _send_error(
                                websocket, "UNAUTHORIZED", "重连凭证不匹配"
                            )
                            continue
                        await _replay_missed_events(
                            db,
                            websocket,
                            room_id=room_id,
                            player_id=bound_player_id,
                            last_sequence=payload.last_event_sequence or 0,
                        )
                        await _send_current_view(
                            db, websocket, room_id, bound_player_id
                        )
                except ValidationError as exc:
                    logger.warning(
                        "ws_invalid_message", event_type=event_type, error=str(exc)
                    )
                except StaleRevisionError as exc:
                    await _send_error(websocket, "STALE_REVISION", str(exc))
                    if bound_player_id is not None:
                        await _send_current_view(
                            db, websocket, room_id, bound_player_id
                        )
                except (
                    RuntimeConflictError,
                    room_service.RoomNotFoundError,
                    room_service.RoomConflictError,
                    room_service.CharacterIncompleteError,
                    room_service.ModuleNotSelectedError,
                ) as exc:
                    await _send_error(websocket, "CONFLICT", str(exc))
                except room_service.RoomAuthorizationError as exc:
                    await _send_error(websocket, "FORBIDDEN", str(exc))
    except WebSocketDisconnect:
        pass
    finally:
        manager.remove(room_id, websocket)
        if bound_player_id is not None:
            async with async_session_factory() as db:
                await room_service.set_player_connected(
                    db, bound_player_id, False
                )
