"""Issue #212 §10 grounded EndingDraft review and confirmation."""

from collaboration_framework.contracts import (
    ConfirmEndingDraftRequest,
    CreateEndingDraftRequest,
)
from collaboration_framework.engine import GameState
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.engine import EndingDraftRecord, GameEvent, GameSession, ModuleVersion
from app.models.room import Room
from app.service import ending as ending_service
from tests.test_engine_runtime import _start_room


async def _open_ending(db: AsyncSession, room_id: str) -> GameSession:
    session = await db.get(GameSession, room_id)
    assert session is not None
    version = await db.get(ModuleVersion, (session.module_id, session.module_version))
    assert version is not None
    required_refs = version.content_json["ending_anchors"][0]["required_fact_refs"]
    state = GameState.model_validate(session.state_json).model_copy(
        update={
            "core_resolved": True,
            "ending_available": True,
            "discovered_facts": tuple(required_refs),
        },
        deep=True,
    )
    session.state_json = state.to_json_dict()
    await db.commit()
    return session


async def test_ending_draft_http_routes(
    client: AsyncClient,
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(db_session, room_number=95, prepare_checkpoint=False)
    session = await _open_ending(db_session, room.id)
    headers = {"X-Reconnect-Token": players[0].reconnect_token}
    draft_response = await client.post(
        f"/api/v1/rooms/{room.id}/ending-drafts",
        headers=headers,
        json={
            "request_id": "http-ending-draft",
            "source_revision": str(session.state_version),
            "player_intent": "现在生成结局与后日谈",
        },
    )
    assert draft_response.status_code == 200, draft_response.text
    draft = draft_response.json()["data"]
    confirm_response = await client.post(
        f"/api/v1/rooms/{room.id}/ending-drafts/{draft['draft_id']}/confirm",
        headers=headers,
        json={
            "request_id": "http-ending-confirm",
            "source_revision": draft["source_revision"],
            "draft_version": draft["version"],
        },
    )
    assert confirm_response.status_code == 200, confirm_response.text
    assert confirm_response.json()["data"]["resolution"]["draft_id"] == draft["draft_id"]


async def test_draft_does_not_end_room_until_confirmed_and_replays(
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(db_session, room_number=93, prepare_checkpoint=False)
    session = await _open_ending(db_session, room.id)
    create = CreateEndingDraftRequest(
        request_id="ending-draft",
        source_revision=str(session.state_version),
        player_intent="我已经变成食尸鬼，现在结束。",
    )

    draft = await ending_service.create_draft(
        db_session, room_id=room.id, player=players[0], request=create
    )

    current = await db_session.get(GameSession, room.id)
    assert current is not None
    await db_session.refresh(current)
    assert GameState.model_validate(current.state_json).phase == "playing"
    assert "变成食尸鬼" not in draft.summary
    assert "变成食尸鬼" not in draft.epilogue

    confirm = ConfirmEndingDraftRequest(
        request_id="ending-confirm",
        source_revision=draft.source_revision,
        draft_version=draft.version,
    )
    result = await ending_service.confirm_draft(
        db_session,
        room_id=room.id,
        draft_id=draft.draft_id,
        player=players[0],
        request=confirm,
    )
    replay = await ending_service.confirm_draft(
        db_session,
        room_id=room.id,
        draft_id=draft.draft_id,
        player=players[0],
        request=confirm,
    )

    assert replay == result
    ended_session = await db_session.get(GameSession, room.id)
    ended_room = await db_session.get(Room, room.id)
    assert ended_session is not None and ended_room is not None
    await db_session.refresh(ended_session)
    await db_session.refresh(ended_room)
    ended = GameState.model_validate(ended_session.state_json)
    assert ended.phase == "ended"
    assert ended.ending_resolution == result.resolution
    assert ended_room.phase == "Completed"
    event = await db_session.scalar(
        select(GameEvent).where(
            GameEvent.room_id == room.id,
            GameEvent.type == "ending.confirmed",
        )
    )
    assert event is not None


async def test_continued_play_expires_revision_bound_draft(
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(db_session, room_number=94, prepare_checkpoint=False)
    session = await _open_ending(db_session, room.id)
    draft = await ending_service.create_draft(
        db_session,
        room_id=room.id,
        player=players[0],
        request=CreateEndingDraftRequest(
            request_id="stale-draft",
            source_revision=str(session.state_version),
            player_intent="先看看如何收尾",
        ),
    )
    await db_session.refresh(session)
    state = GameState.model_validate(session.state_json).model_copy(
        update={"event_sequence": session.state_version + 1}, deep=True
    )
    session.state_json = state.to_json_dict()
    session.state_version += 1
    db_session.add(
        GameEvent(
            room_id=room.id,
            sequence=session.state_version,
            event_id="continued-play",
            client_action_id="continued-play",
            type="action.resolved",
            actor_id=next(iter(state.actors)),
            visibility="public",
            cause="continued_play",
            payload={},
        )
    )
    await db_session.commit()

    try:
        await ending_service.confirm_draft(
            db_session,
            room_id=room.id,
            draft_id=draft.draft_id,
            player=players[0],
            request=ConfirmEndingDraftRequest(
                request_id="stale-confirm",
                source_revision=draft.source_revision,
                draft_version=draft.version,
            ),
        )
    except ending_service.EndingDraftStaleError:
        pass
    else:
        raise AssertionError("continued play must expire an old EndingDraft")

    record = await db_session.get(EndingDraftRecord, (room.id, draft.draft_id))
    assert record is not None and record.status == "expired"
    await db_session.refresh(session)
    assert GameState.model_validate(session.state_json).phase == "playing"
