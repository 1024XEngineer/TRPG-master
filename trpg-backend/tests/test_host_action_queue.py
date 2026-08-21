"""主持行动持久化队列（issue #397）。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from collaboration_framework.contracts import ContractError
from sqlalchemy.ext.asyncio import AsyncSession

from app.controller import ws as ws_controller
from app.core.turn import ActorResolutionError
from app.service import host_action_queue
from app.service.host_action_queue import HostActionQueueError
from tests.test_engine_runtime import _start_room


@pytest.mark.asyncio
async def test_enqueue_is_fifo_and_idempotent(db_session: AsyncSession) -> None:
    room, players, _ = await _start_room(
        db_session,
        room_number=3971,
        player_count=2,
        prepare_checkpoint=False,
    )

    first, created = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="action-a",
        utterance="我搜查客厅",
    )
    assert created
    second, created = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
        actor_id="actor-b",
        client_action_id="action-b",
        utterance="我查看书桌",
    )
    assert created
    again, created = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="action-a",
        utterance="我搜查客厅",
    )
    assert not created
    assert again.item_id == first.item_id

    queued = await host_action_queue.list_queued(db_session, room.id)
    assert [item.client_action_id for item in queued] == ["action-a", "action-b"]
    assert second.position > first.position


@pytest.mark.asyncio
async def test_player_can_replace_queued_item_without_losing_place(
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(
        db_session,
        room_number=3972,
        player_count=2,
        prepare_checkpoint=False,
    )
    first, _ = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="action-a1",
        utterance="我先看窗",
    )
    await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
        actor_id="actor-b",
        client_action_id="action-b",
        utterance="我搜查抽屉",
    )
    replaced, created = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="action-a2",
        utterance="我改去翻书架",
    )
    assert created
    assert replaced.item_id == first.item_id
    assert replaced.position == first.position
    queued = await host_action_queue.list_queued(db_session, room.id)
    assert [item.client_action_id for item in queued] == ["action-a2", "action-b"]
    assert queued[0].utterance == "我改去翻书架"


@pytest.mark.asyncio
async def test_queue_rejects_when_every_player_already_has_an_item(
    db_session: AsyncSession,
) -> None:
    room, players, _ = await _start_room(
        db_session,
        room_number=3973,
        player_count=2,
        prepare_checkpoint=False,
    )
    await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="action-a",
        utterance="我搜查客厅",
    )
    await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
        actor_id="actor-b",
        client_action_id="action-b",
        utterance="我查看书桌",
    )
    with pytest.raises(HostActionQueueError) as raised:
        await host_action_queue.enqueue(
            db_session,
            room_id=room.id,
            player_id="ghost-player",
            actor_id="actor-ghost",
            client_action_id="action-overflow",
            utterance="这句不该进队",
        )
    assert raised.value.code == "ACTION_QUEUE_FULL"
    # replace keeps the cap: same player updating the existing item is allowed
    replaced, _ = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
        actor_id="actor-b",
        client_action_id="action-b2",
        utterance="我改口搜查书桌",
    )
    assert replaced.client_action_id == "action-b2"


@pytest.mark.asyncio
async def test_cancel_and_discard_player_queued_items(db_session: AsyncSession) -> None:
    room, players, _ = await _start_room(
        db_session,
        room_number=3974,
        player_count=2,
        prepare_checkpoint=False,
    )
    await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="action-a",
        utterance="我搜查客厅",
    )
    await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
        actor_id="actor-b",
        client_action_id="action-b",
        utterance="我查看书桌",
    )
    assert await host_action_queue.cancel(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        client_action_id="action-a",
    )
    assert not await host_action_queue.cancel(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
        client_action_id="action-a",
    )
    remaining = await host_action_queue.list_queued(db_session, room.id)
    assert [item.client_action_id for item in remaining] == ["action-b"]
    discarded = await host_action_queue.discard_player(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
    )
    assert discarded == 1
    assert await host_action_queue.list_queued(db_session, room.id) == []
    peeked = await host_action_queue.peek_next(db_session, room.id)
    assert peeked is None


async def _enqueue_one(db_session: AsyncSession, room_number: int) -> tuple[str, str]:
    room, players, _ = await _start_room(
        db_session,
        room_number=room_number,
        player_count=1,
        prepare_checkpoint=False,
    )
    await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="queued-action",
        utterance="我搜查客厅",
    )
    return room.id, players[0].id


def _stub_player_view(current_player_view):  # noqa: ANN001
    return SimpleNamespace(current_player_view=current_player_view)


@pytest.mark.asyncio
async def test_drain_keeps_queued_item_when_player_view_is_temporarily_unavailable(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id, _ = await _enqueue_one(db_session, 3975)

    async def boom(*, room_id: str, player_id: str):  # noqa: ARG001
        raise ContractError(f"房间运行时不存在: {room_id}")

    monkeypatch.setattr(ws_controller, "session_view_application", _stub_player_view(boom))
    await ws_controller._drain_host_action_queue(room_id)

    queued = await host_action_queue.peek_next(db_session, room_id)
    assert queued is not None
    assert queued.client_action_id == "queued-action"
    assert queued.status == "queued"


@pytest.mark.asyncio
async def test_drain_discards_queued_item_when_actor_is_unbound(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id, _ = await _enqueue_one(db_session, 3976)

    async def unbound(*, room_id: str, player_id: str):  # noqa: ARG001
        raise ActorResolutionError("当前玩家没有唯一绑定的局内 Actor")

    monkeypatch.setattr(ws_controller, "session_view_application", _stub_player_view(unbound))
    await ws_controller._drain_host_action_queue(room_id)

    assert await host_action_queue.peek_next(db_session, room_id) is None


@pytest.mark.asyncio
async def test_drain_discards_queued_item_when_actor_id_changed(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room_id, _ = await _enqueue_one(db_session, 3977)

    async def rebound(*, room_id: str, player_id: str):  # noqa: ARG001
        return SimpleNamespace(self_actor=SimpleNamespace(id="actor-other"), revision="9")

    monkeypatch.setattr(ws_controller, "session_view_application", _stub_player_view(rebound))
    await ws_controller._drain_host_action_queue(room_id)

    assert await host_action_queue.peek_next(db_session, room_id) is None
