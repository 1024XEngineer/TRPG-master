"""主持行动持久化队列（issue #397）。"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from collaboration_framework.contracts import ContractError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.controller import ws as ws_controller
from app.core.turn import ActorResolutionError
from app.dto.ws import ActionRecipientPayload
from app.models.event import Event
from app.service import host_action_queue
from app.service.host_action_queue import HostActionQueueError
from tests.test_engine_runtime import _start_room
from tests.test_npc_dialogue import _view

_KEEPER_RECIPIENT = ActionRecipientPayload(kind="keeper", entity_id=None, explicit=True)
_NPC_RECIPIENT = ActionRecipientPayload(kind="npc", entity_id="caretaker", explicit=True)


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
        recipient=_KEEPER_RECIPIENT,
    )
    assert created
    second, created = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
        actor_id="actor-b",
        client_action_id="action-b",
        utterance="我查看书桌",
        recipient=_KEEPER_RECIPIENT,
    )
    assert created
    again, created = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="action-a",
        utterance="我搜查客厅",
        recipient=_KEEPER_RECIPIENT,
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
        recipient=_KEEPER_RECIPIENT,
    )
    await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
        actor_id="actor-b",
        client_action_id="action-b",
        utterance="我搜查抽屉",
        recipient=_KEEPER_RECIPIENT,
    )
    replaced, created = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="action-a2",
        utterance="我改去翻书架",
        recipient=_KEEPER_RECIPIENT,
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
        recipient=_KEEPER_RECIPIENT,
    )
    await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
        actor_id="actor-b",
        client_action_id="action-b",
        utterance="我查看书桌",
        recipient=_KEEPER_RECIPIENT,
    )
    with pytest.raises(HostActionQueueError) as raised:
        await host_action_queue.enqueue(
            db_session,
            room_id=room.id,
            player_id="ghost-player",
            actor_id="actor-ghost",
            client_action_id="action-overflow",
            utterance="这句不该进队",
            recipient=_KEEPER_RECIPIENT,
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
        recipient=_KEEPER_RECIPIENT,
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
        recipient=_KEEPER_RECIPIENT,
    )
    await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
        actor_id="actor-b",
        client_action_id="action-b",
        utterance="我查看书桌",
        recipient=_KEEPER_RECIPIENT,
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
        recipient=_KEEPER_RECIPIENT,
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


@pytest.mark.asyncio
async def test_npc_queue_claim_is_atomic_and_expired_lease_recovers(
    db_session: AsyncSession,
) -> None:
    """两个 drain 竞争时只允许一个领取；lease 过期后同一项可以再次领取。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3978,
        player_count=1,
        prepare_checkpoint=False,
    )
    await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="npc-action",
        utterance="请记住蓝色钟摆",
        recipient=_NPC_RECIPIENT,
    )
    sessions = async_sessionmaker(db_session.bind, expire_on_commit=False)

    async def compete():
        async with sessions() as session:
            candidate = await host_action_queue.peek_next(session, room.id)
            assert candidate is not None
            return await host_action_queue.claim_npc(session, candidate)

    winners = await asyncio.gather(compete(), compete())
    claimed = [item for item in winners if item is not None]
    assert len(claimed) == 1
    assert claimed[0].attempt_count == 1

    async with sessions() as session:
        expired = await host_action_queue.get_by_client_action(session, room.id, "npc-action")
        assert expired is not None
        expired.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()
        candidate = await host_action_queue.peek_next(session, room.id)
        assert candidate is not None
        recovered = await host_action_queue.claim_npc(session, candidate)
        assert recovered is not None
        assert recovered.attempt_count == 2


@pytest.mark.asyncio
async def test_npc_queue_waiting_head_blocks_later_items_and_schedules_recovery(
    db_session: AsyncSession,
) -> None:
    """未过期 lease 必须保留 FIFO 位置，重启恢复时间取自持久化 lease。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3979,
        player_count=2,
        prepare_checkpoint=False,
    )
    first, _ = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="npc-first",
        utterance="先和守墓人说话",
        recipient=_NPC_RECIPIENT,
    )
    await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[1].id,
        actor_id="actor-b",
        client_action_id="keeper-second",
        utterance="随后调查书架",
        recipient=_KEEPER_RECIPIENT,
    )
    claimed = await host_action_queue.claim_npc(db_session, first)
    assert claimed is not None

    # 队首仍由旧 worker 的 lease 持有时，第二项不能绕过它执行。
    assert await host_action_queue.peek_next(db_session, room.id) is None
    schedule = await host_action_queue.recovery_schedule(db_session)
    room_delay = dict(schedule)[room.id]
    assert 170 <= room_delay <= 180

    claimed.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    await db_session.commit()
    recovered_head = await host_action_queue.peek_next(db_session, room.id)
    assert recovered_head is not None
    assert recovered_head.client_action_id == "npc-first"


@pytest.mark.asyncio
async def test_claim_retryable_failure_after_sqlite_reload(
    db_session: AsyncSession,
) -> None:
    """SQLite 读出的 naive datetime 不能让二次领取在 Python 侧比较崩溃。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3981,
        player_count=1,
        prepare_checkpoint=False,
    )
    item, _ = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="retry-reload",
        utterance="跟邻居打个招呼",
        recipient=_KEEPER_RECIPIENT,
    )
    claimed = await host_action_queue.claim(
        db_session, item, recipient_kind="keeper", lease_seconds=180
    )
    assert claimed is not None
    await host_action_queue.mark_npc_retryable(db_session, claimed, delay_seconds=0)
    room_id = room.id
    db_session.expire_all()
    head = await host_action_queue.peek_next(db_session, room_id)
    assert head is not None
    recovered = await host_action_queue.claim(
        db_session, head, recipient_kind="keeper", lease_seconds=180
    )
    assert recovered is not None
    assert recovered.status == "processing"
    assert recovered.attempt_count == 2


@pytest.mark.asyncio
async def test_npc_cancel_before_player_event_persists_nothing(
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """受众冻结期间收到取消时，玩家原话和 NPC 回复都不能落库。"""

    room, players, _ = await _start_room(
        db_session,
        room_number=3980,
        player_count=1,
        prepare_checkpoint=False,
    )
    item, _ = await host_action_queue.enqueue(
        db_session,
        room_id=room.id,
        player_id=players[0].id,
        actor_id="actor-a",
        client_action_id="npc-cancel-before-event",
        utterance="这句话不应发生",
        recipient=_NPC_RECIPIENT,
    )
    base_view = _view()
    view = base_view.model_copy(
        update={
            "room_id": room.id,
            "player_id": players[0].id,
            "actor_id": "actor-a",
            "self_actor": base_view.self_actor.model_copy(update={"id": "actor-a"}),
        }
    )

    async def cancel_while_freezing(db: AsyncSession, **kwargs):  # noqa: ANN003, ARG001
        await host_action_queue.cancel(
            db,
            room_id=room.id,
            player_id=players[0].id,
            client_action_id=item.client_action_id,
        )
        return (players[0].id,), ("actor-a",)

    monkeypatch.setattr(ws_controller, "_npc_dialogue_audience", cancel_while_freezing)
    await ws_controller._run_queued_host_action(db_session, item, view)

    persisted = await db_session.scalar(
        select(func.count())
        .select_from(Event)
        .where(
            Event.room_id == room.id,
            Event.event_type.in_(("dialogue.player", "dialogue.npc")),
        )
    )
    cancelled = await host_action_queue.get_by_client_action(
        db_session,
        room.id,
        item.client_action_id,
    )
    assert persisted == 0
    assert cancelled is not None
    assert cancelled.status == "cancelled"
