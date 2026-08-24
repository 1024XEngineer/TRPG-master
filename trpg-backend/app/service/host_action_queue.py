"""房间级主持行动队列（issue #397）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Literal, cast

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.dto.ws import ActionRecipientPayload, RoomActionQueueItemPayload
from app.models.engine import HostActionQueueItem
from app.models.room import Player

_QUEUED = "queued"


class HostActionQueueError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _payload(item: HostActionQueueItem) -> RoomActionQueueItemPayload:
    return RoomActionQueueItemPayload(
        player_id=item.player_id,
        actor_id=item.actor_id,
        client_action_id=item.client_action_id,
        recipient=ActionRecipientPayload(
            kind=cast(Literal["keeper", "npc"], item.recipient_kind),
            entity_id=item.recipient_entity_id,
            explicit=item.recipient_explicit,
        ),
        position=item.position,
        utterance=item.utterance,
        accepted_at=item.created_at,
    )


async def list_queued(
    db: AsyncSession,
    room_id: str,
) -> list[RoomActionQueueItemPayload]:
    rows = (
        await db.scalars(
            select(HostActionQueueItem)
            .where(
                HostActionQueueItem.room_id == room_id,
                HostActionQueueItem.status == _QUEUED,
            )
            .order_by(HostActionQueueItem.position.asc())
        )
    ).all()
    return [_payload(item) for item in rows]


async def get_queued_by_client_action(
    db: AsyncSession,
    room_id: str,
    client_action_id: str,
) -> HostActionQueueItem | None:
    return await db.scalar(
        select(HostActionQueueItem).where(
            HostActionQueueItem.room_id == room_id,
            HostActionQueueItem.client_action_id == client_action_id,
            HostActionQueueItem.status == _QUEUED,
        )
    )


async def enqueue(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
    actor_id: str,
    client_action_id: str,
    utterance: str,
    recipient: ActionRecipientPayload,
) -> tuple[HostActionQueueItem, bool]:
    """Accept a host action into the room FIFO.

    Returns (item, created). created=False means the same client_action_id was
    already queued (idempotent) or this player replaced their existing item.
    Replacement keeps position and is treated as created=True so the new
    utterance can be published.
    """

    existing_id = await get_queued_by_client_action(db, room_id, client_action_id)
    if existing_id is not None:
        return existing_id, False

    own = await db.scalar(
        select(HostActionQueueItem).where(
            HostActionQueueItem.room_id == room_id,
            HostActionQueueItem.player_id == player_id,
            HostActionQueueItem.status == _QUEUED,
        )
    )
    now = datetime.now(UTC)
    if own is not None:
        own.client_action_id = client_action_id
        own.actor_id = actor_id
        own.utterance = utterance
        own.recipient_kind = recipient.kind
        own.recipient_entity_id = recipient.entity_id
        own.recipient_explicit = recipient.explicit
        own.updated_at = now
        await db.commit()
        await db.refresh(own)
        return own, True

    queued_count = await db.scalar(
        select(func.count())
        .select_from(HostActionQueueItem)
        .where(
            HostActionQueueItem.room_id == room_id,
            HostActionQueueItem.status == _QUEUED,
        )
    )
    player_count = await db.scalar(
        select(func.count()).select_from(Player).where(Player.room_id == room_id)
    )
    if (queued_count or 0) >= (player_count or 0):
        raise HostActionQueueError(
            "ACTION_QUEUE_FULL",
            "主持行动队列已满，请等待当前排队处理后再提交",
        )

    max_position = await db.scalar(
        select(func.max(HostActionQueueItem.position)).where(HostActionQueueItem.room_id == room_id)
    )
    item = HostActionQueueItem(
        room_id=room_id,
        item_id=str(uuid.uuid4()),
        client_action_id=client_action_id,
        player_id=player_id,
        actor_id=actor_id,
        utterance=utterance,
        recipient_kind=recipient.kind,
        recipient_entity_id=recipient.entity_id,
        recipient_explicit=recipient.explicit,
        position=(max_position or 0) + 1,
        status=_QUEUED,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raced = await get_queued_by_client_action(db, room_id, client_action_id)
        if raced is not None:
            return raced, False
        raise HostActionQueueError(
            "ACTION_QUEUE_FULL",
            "主持行动队列已满，请等待当前排队处理后再提交",
        ) from exc
    await db.refresh(item)
    return item, True


async def cancel(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
    client_action_id: str,
) -> bool:
    item = await get_queued_by_client_action(db, room_id, client_action_id)
    if item is None or item.player_id != player_id:
        return False
    item.status = "cancelled"
    item.updated_at = datetime.now(UTC)
    await db.commit()
    return True


async def peek_next(db: AsyncSession, room_id: str) -> HostActionQueueItem | None:
    return await db.scalar(
        select(HostActionQueueItem)
        .where(
            HostActionQueueItem.room_id == room_id,
            HostActionQueueItem.status == _QUEUED,
        )
        .order_by(HostActionQueueItem.position.asc())
        .limit(1)
    )


async def mark_started(db: AsyncSession, item: HostActionQueueItem) -> None:
    item.status = "started"
    item.updated_at = datetime.now(UTC)
    await db.commit()


async def discard(db: AsyncSession, item: HostActionQueueItem) -> None:
    item.status = "discarded"
    item.updated_at = datetime.now(UTC)
    await db.commit()


async def discard_player(
    db: AsyncSession,
    *,
    room_id: str,
    player_id: str,
) -> int:
    rows = (
        await db.scalars(
            select(HostActionQueueItem).where(
                HostActionQueueItem.room_id == room_id,
                HostActionQueueItem.player_id == player_id,
                HostActionQueueItem.status == _QUEUED,
            )
        )
    ).all()
    now = datetime.now(UTC)
    for item in rows:
        item.status = "discarded"
        item.updated_at = now
    if rows:
        await db.commit()
    return len(rows)
