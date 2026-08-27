"""#421-D：必要追问后续作同一次主持行动。"""

from __future__ import annotations

import pytest
from collaboration_framework.contracts import PlayerView
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.controller import ws as ws_controller
from app.core.host_entry import (
    DeterministicHostEntryModel,
    HostEntryDecision,
    HostEntryRouter,
    HostPublicContext,
)
from app.dto.ws import ActionRecipientPayload
from app.models.event import Event
from app.models.room import Player
from app.service import host_action_queue
from app.service.action_lock import action_lock_manager
from tests.test_engine_runtime import _start_room

_KEEPER = ActionRecipientPayload(kind="keeper", entity_id=None, explicit=True)


async def _room_views(
    db: AsyncSession, room_number: int, player_count: int = 1
) -> tuple[str, list[Player], list[PlayerView]]:
    room, players, _ = await _start_room(
        db,
        room_number=room_number,
        player_count=player_count,
        prepare_checkpoint=False,
    )
    views = [
        await ws_controller.session_view_application.current_player_view(
            room_id=room.id,
            player_id=player.id,
        )
        for player in players
    ]
    return str(room.id), players, views


async def _enqueue_keeper(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
    actor_id: str,
    client_action_id: str,
    utterance: str,
):
    return await host_action_queue.enqueue(
        db,
        room_id=room_id,
        player_id=player_id,
        actor_id=actor_id,
        client_action_id=client_action_id,
        utterance=utterance,
        recipient=_KEEPER,
    )


async def _narration_by_correlation(db: AsyncSession, room_id: str) -> dict[str, str]:
    rows = (
        await db.scalars(
            select(Event).where(Event.room_id == room_id, Event.event_type == "narration.push")
        )
    ).all()
    return {
        str(event.correlation_id): str(event.payload.get("text") or "")
        for event in rows
        if event.correlation_id and event.correlation_id != "game-opening"
    }


def _install_router(monkeypatch: pytest.MonkeyPatch) -> HostEntryRouter:
    router = HostEntryRouter(DeterministicHostEntryModel())
    monkeypatch.setattr(ws_controller, "_get_host_entry_router", lambda: router)
    monkeypatch.setattr(ws_controller, "_host_entry_router", router)
    action_lock_manager._locks.clear()
    return router


@pytest.mark.asyncio
async def test_ambiguous_keeper_action_asks_once_and_waits(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4761)
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[0].id,
        actor_id=views[0].self_actor.id,
        client_action_id="look-that",
        utterance="看那个",
    )
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()

    item = await host_action_queue.get_by_client_action(db_session, room_id, "look-that")
    texts = await _narration_by_correlation(db_session, room_id)
    state = await ws_controller._current_room_action_state(db_session, room_id)
    assert item is not None
    assert item.status == "needs_clarification"
    assert item.execution_route == "needs_clarification"
    assert texts.get("look-that:clarify") == "你具体指的是哪一个？"
    assert "look-that" not in texts
    assert state is not None
    assert state.status == "awaiting_player"
    assert state.client_action_id == "look-that"
    assert await host_action_queue.peek_next(db_session, room_id) is None


@pytest.mark.asyncio
async def test_clarification_answer_continues_same_action(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4762)
    player_id = players[0].id
    actor_id = views[0].self_actor.id
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=player_id,
        actor_id=actor_id,
        client_action_id="look-that",
        utterance="看那个",
    )
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()
    view = views[0]
    await ws_controller._continue_host_clarification(
        db_session,
        None,
        room_id=room_id,
        player_id=player_id,
        actor_id=actor_id,
        client_action_id="look-that-answer",
        utterance="邻居",
        player_view=view,
    )
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()

    item = await host_action_queue.get_by_client_action(db_session, room_id, "look-that")
    texts = await _narration_by_correlation(db_session, room_id)
    assert item is not None
    assert item.status == "completed"
    assert item.continuation_text == "邻居"
    assert item.execution_route == "direct_response"
    assert texts["look-that:clarify"] == "你具体指的是哪一个？"
    assert texts["look-that"] == "明白了，就按这个来。"
    answer_item = await host_action_queue.get_by_client_action(
        db_session, room_id, "look-that-answer"
    )
    assert answer_item is None


@pytest.mark.asyncio
async def test_correction_does_not_repeat_clarification(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4763)
    player_id = players[0].id
    actor_id = views[0].self_actor.id
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=player_id,
        actor_id=actor_id,
        client_action_id="look-that",
        utterance="看那个",
    )
    await ws_controller._drain_host_action_queue(room_id)
    await ws_controller._continue_host_clarification(
        db_session,
        None,
        room_id=room_id,
        player_id=player_id,
        actor_id=actor_id,
        client_action_id="look-that-fix",
        utterance="不是右边，是左边那个",
        player_view=views[0],
    )
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()
    texts = await _narration_by_correlation(db_session, room_id)
    clarify_events = [key for key in texts if str(key).endswith(":clarify")]
    assert len(clarify_events) == 1
    item = await host_action_queue.get_by_client_action(db_session, room_id, "look-that")
    assert item is not None
    assert item.status == "completed"


@pytest.mark.asyncio
async def test_later_player_cannot_cut_in_during_clarification(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4764, player_count=2)
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[0].id,
        actor_id=views[0].self_actor.id,
        client_action_id="look-first",
        utterance="看那个",
    )
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[1].id,
        actor_id=views[1].self_actor.id,
        client_action_id="greet-second",
        utterance="跟邻居打个招呼",
    )
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()
    second = await host_action_queue.get_by_client_action(db_session, room_id, "greet-second")
    assert second is not None
    assert second.status == "queued"
    assert await host_action_queue.peek_next(db_session, room_id) is None


@pytest.mark.asyncio
async def test_ordinary_greeting_still_skips_clarification(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4765)
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[0].id,
        actor_id=views[0].self_actor.id,
        client_action_id="greet",
        utterance="跟邻居打个招呼",
    )
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()
    item = await host_action_queue.get_by_client_action(db_session, room_id, "greet")
    texts = await _narration_by_correlation(db_session, room_id)
    assert item is not None
    assert item.status == "completed"
    assert item.execution_route == "direct_response"
    assert texts == {"greet": "对方礼貌地点了点头。"}


@pytest.mark.asyncio
async def test_host_entry_router_clarifies_then_refuses_second_ask() -> None:
    router = HostEntryRouter(DeterministicHostEntryModel())
    first, provenance = await router.decide(HostPublicContext(current_keeper_text="看那个"))
    assert first.route == "needs_clarification"
    assert provenance == "model_clarify"
    second, _ = await router.decide(
        HostPublicContext(
            current_keeper_text="看那个",
            clarification_question="你具体指的是哪一个？",
            player_answer="邻居",
        )
    )
    assert second.route == "direct_response"
    with pytest.raises(ValueError):
        HostEntryDecision(route="needs_clarification", text=None)
