"""#421-E 前置：主持入口与房间 FIFO 的排队、失败和恢复。"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from collaboration_framework.contracts import PlayerView
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.controller import ws as ws_controller
from app.core.host_entry import (
    DeterministicHostEntryModel,
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


class _RecordingHostEntryModel:
    def __init__(self) -> None:
        self.calls = 0
        self.contexts: list[HostPublicContext] = []
        self._inner = DeterministicHostEntryModel()

    async def generate(self, context: HostPublicContext) -> Mapping[str, object]:
        self.calls += 1
        self.contexts.append(context)
        return await self._inner.generate(context)


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
    item, created = await host_action_queue.enqueue(
        db,
        room_id=room_id,
        player_id=player_id,
        actor_id=actor_id,
        client_action_id=client_action_id,
        utterance=utterance,
        recipient=_KEEPER,
    )
    return item, created


async def _narration_events(db: AsyncSession, room_id: str) -> list[Event]:
    rows = (
        await db.scalars(
            select(Event)
            .where(Event.room_id == room_id, Event.event_type == "narration.push")
            .order_by(Event.created_at, Event.id)
        )
    ).all()
    return [event for event in rows if event.correlation_id != "game-opening"]


def _install_router(monkeypatch: pytest.MonkeyPatch) -> _RecordingHostEntryModel:
    model = _RecordingHostEntryModel()
    router = HostEntryRouter(model)
    monkeypatch.setattr(ws_controller, "_get_host_entry_router", lambda: router)
    monkeypatch.setattr(ws_controller, "_host_entry_router", router)
    action_lock_manager._locks.clear()
    return model


@pytest.mark.asyncio
async def test_frozen_direct_response_retries_without_second_router_call(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """路线冻结后中途崩溃：恢复使用已保存文本，不得重新询问模型。"""

    model = _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4641)
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[0].id,
        actor_id=views[0].self_actor.id,
        client_action_id="greet-crash",
        utterance="跟邻居打个招呼",
    )
    original = ws_controller._run_direct_host_action
    runs = {"n": 0}

    async def flaky(db, item, view, websocket, **kwargs):  # noqa: ANN001
        runs["n"] += 1
        if runs["n"] == 1:
            raise RuntimeError("simulated crash after freeze")
        return await original(db, item, view, websocket, **kwargs)

    monkeypatch.setattr(ws_controller, "_run_direct_host_action", flaky)
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()

    item = await host_action_queue.get_by_client_action(db_session, room_id, "greet-crash")
    events = await _narration_events(db_session, room_id)
    assert model.calls == 1
    assert runs["n"] == 2
    assert item is not None
    assert item.status == "completed"
    assert item.execution_route == "direct_response"
    assert item.direct_response_text == "对方礼貌地点了点头。"
    assert [event.correlation_id for event in events] == ["greet-crash"]
    assert events[0].payload["text"] == "对方礼貌地点了点头。"


@pytest.mark.asyncio
async def test_broadcast_failure_after_commit_keeps_completed_direct_response(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4642)
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[0].id,
        actor_id=views[0].self_actor.id,
        client_action_id="greet-broadcast",
        utterance="跟邻居打个招呼",
    )

    async def boom_emit(*args, **kwargs):  # noqa: ANN002, ARG001
        raise RuntimeError("broadcast failed after commit")

    monkeypatch.setattr(ws_controller, "_emit_turn_narration", boom_emit)
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()

    item = await host_action_queue.get_by_client_action(db_session, room_id, "greet-broadcast")
    events = await _narration_events(db_session, room_id)
    assert item is not None
    assert item.status == "completed"
    assert len(events) == 1


@pytest.mark.asyncio
async def test_duplicate_client_action_id_does_not_rewrite_completed_direct_response(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4643)
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[0].id,
        actor_id=views[0].self_actor.id,
        client_action_id="greet-once",
        utterance="跟邻居打个招呼",
    )
    await ws_controller._drain_host_action_queue(room_id)
    player_id = players[0].id
    actor_id = views[0].self_actor.id
    db_session.expire_all()
    _, created = await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=player_id,
        actor_id=actor_id,
        client_action_id="greet-once",
        utterance="跟邻居打个招呼",
    )
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()

    events = await _narration_events(db_session, room_id)
    again = await host_action_queue.get_by_client_action(db_session, room_id, "greet-once")
    assert created is False
    assert again is not None
    assert again.status == "completed"
    assert model.calls == 1
    assert [event.correlation_id for event in events] == ["greet-once"]


@pytest.mark.asyncio
async def test_existing_event_only_completes_queue_on_recovery(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4644)
    item, _ = await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[0].id,
        actor_id=views[0].self_actor.id,
        client_action_id="greet-replay",
        utterance="跟邻居打个招呼",
    )
    await host_action_queue.save_execution_route(
        db_session,
        item,
        route="direct_response",
        text="对方礼貌地点了点头。",
        provenance="model_direct",
    )
    event = Event(
        room_id=room_id,
        player_id=players[0].id,
        event_type="narration.push",
        correlation_id="greet-replay",
        visibility="public",
        actor_id=views[0].self_actor.id,
        scene_id=views[0].scene.id,
        view_revision=views[0].revision,
        payload={"messageId": "greet-replay", "text": "对方礼貌地点了点头。"},
    )
    db_session.add(event)
    await db_session.commit()
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()

    recovered = await host_action_queue.get_by_client_action(db_session, room_id, "greet-replay")
    count = await db_session.scalar(
        select(func.count())
        .select_from(Event)
        .where(
            Event.room_id == room_id,
            Event.event_type == "narration.push",
            Event.correlation_id == "greet-replay",
        )
    )
    assert recovered is not None
    assert recovered.status == "completed"
    assert model.calls == 0
    assert count == 1


@pytest.mark.asyncio
async def test_fifo_direct_response_then_legacy_does_not_cut_in_line(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4645, player_count=2)
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[0].id,
        actor_id=views[0].self_actor.id,
        client_action_id="greet-first",
        utterance="跟邻居打个招呼",
    )
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[1].id,
        actor_id=views[1].self_actor.id,
        client_action_id="search-second",
        utterance="搜索书桌里的暗格",
    )
    order: list[str] = []
    original_direct = ws_controller._run_direct_host_action

    async def record_direct(db, item, view, websocket, **kwargs):  # noqa: ANN001
        order.append(item.client_action_id)
        return await original_direct(db, item, view, websocket, **kwargs)

    async def record_start(**kwargs):  # noqa: ANN003
        order.append(kwargs["client_action_id"])
        return SimpleNamespace(waiting_for_player=False)

    async def skip_send(*args, **kwargs):  # noqa: ANN002, ARG001
        return True

    monkeypatch.setattr(ws_controller, "_run_direct_host_action", record_direct)
    monkeypatch.setattr(ws_controller.action_plan_turn_application, "start", record_start)
    monkeypatch.setattr(ws_controller, "_send_action_plan_result", skip_send)
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()

    first = await host_action_queue.get_by_client_action(db_session, room_id, "greet-first")
    second = await host_action_queue.get_by_client_action(db_session, room_id, "search-second")
    events = await _narration_events(db_session, room_id)
    assert order == ["greet-first", "search-second"]
    assert model.calls == 2
    assert first is not None and first.status == "completed"
    assert first.execution_route == "direct_response"
    assert second is not None and second.status == "completed"
    assert second.execution_route == "delegate_to_legacy"
    assert [event.correlation_id for event in events] == ["greet-first"]


@pytest.mark.asyncio
async def test_failed_direct_response_unblocks_following_queue_item(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4646, player_count=2)
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[0].id,
        actor_id=views[0].self_actor.id,
        client_action_id="greet-poison",
        utterance="跟邻居打个招呼",
    )
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[1].id,
        actor_id=views[1].self_actor.id,
        client_action_id="greet-next",
        utterance="跟邻居打个招呼",
    )
    original = ws_controller._run_direct_host_action

    async def poison_first(db, item, view, websocket, **kwargs):  # noqa: ANN001
        if item.client_action_id == "greet-poison":
            raise RuntimeError("poisoned head")
        return await original(db, item, view, websocket, **kwargs)

    monkeypatch.setattr(ws_controller, "_run_direct_host_action", poison_first)
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()

    failed = await host_action_queue.get_by_client_action(db_session, room_id, "greet-poison")
    nxt = await host_action_queue.get_by_client_action(db_session, room_id, "greet-next")
    events = await _narration_events(db_session, room_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.attempt_count == 2
    assert nxt is not None and nxt.status == "completed"
    assert [event.correlation_id for event in events] == ["greet-next"]
    assert await host_action_queue.peek_next(db_session, room_id) is None


@pytest.mark.asyncio
async def test_later_direct_response_sees_previous_public_narration(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _install_router(monkeypatch)
    room_id, players, views = await _room_views(db_session, 4647, player_count=2)
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[0].id,
        actor_id=views[0].self_actor.id,
        client_action_id="greet-a",
        utterance="跟邻居打个招呼",
    )
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[1].id,
        actor_id=views[1].self_actor.id,
        client_action_id="greet-b",
        utterance="跟邻居打个招呼",
    )
    await ws_controller._drain_host_action_queue(room_id)
    db_session.expire_all()

    assert model.calls == 2
    second_history = model.contexts[1].recent_history
    assert any(
        entry.text == "对方礼貌地点了点头。" and entry.source == "keeper_narration"
        for entry in second_history
    )


@pytest.mark.asyncio
async def test_keeper_processing_lease_blocks_later_queue_item(
    db_session: AsyncSession,
) -> None:
    room_id, players, views = await _room_views(db_session, 4648, player_count=2)
    first, _ = await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[0].id,
        actor_id=views[0].self_actor.id,
        client_action_id="keeper-first",
        utterance="跟邻居打个招呼",
    )
    await _enqueue_keeper(
        db_session,
        room_id=room_id,
        player_id=players[1].id,
        actor_id=views[1].self_actor.id,
        client_action_id="keeper-second",
        utterance="跟邻居打个招呼",
    )
    claimed = await host_action_queue.claim(
        db_session, first, recipient_kind="keeper", lease_seconds=180
    )
    assert claimed is not None
    assert await host_action_queue.peek_next(db_session, room_id) is None
    schedule = dict(await host_action_queue.recovery_schedule(db_session))
    assert 170 <= schedule[room_id] <= 180

    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    recovered = await host_action_queue.peek_next(db_session, room_id)
    assert recovered is not None
    assert recovered.client_action_id == "keeper-first"
