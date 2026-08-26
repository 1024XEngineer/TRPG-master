"""房间级主持行动队列（issue #397）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from sqlalchemy import and_, func, or_, select, update
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
            HostActionQueueItem.status.in_(("queued", "processing", "retryable_failure")),
        )
    )


async def get_by_client_action(
    db: AsyncSession,
    room_id: str,
    client_action_id: str,
) -> HostActionQueueItem | None:
    """读取任意状态的幂等队列项，终态重复提交也不能触发新任务。"""

    return await db.scalar(
        select(HostActionQueueItem).where(
            HostActionQueueItem.room_id == room_id,
            HostActionQueueItem.client_action_id == client_action_id,
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

    existing_id = await get_by_client_action(db, room_id, client_action_id)
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
        # Replacing a queued utterance is a new semantic request at the same FIFO
        # position.  Never retain a route, generated text, or old result IDs.
        own.execution_route = "unresolved"
        own.direct_response_text = None
        own.execution_provenance = None
        own.result_event_ids = []
        own.attempt_count = 0
        own.next_attempt_at = None
        own.lease_owner = None
        own.lease_expires_at = None
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
        raced = await get_by_client_action(db, room_id, client_action_id)
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
    item.lease_owner = None
    item.lease_expires_at = None
    item.next_attempt_at = None
    item.updated_at = datetime.now(UTC)
    await db.commit()
    return True


async def peek_next(db: AsyncSession, room_id: str) -> HostActionQueueItem | None:
    """只检查 FIFO 队首；队首尚在 lease/退避期时禁止后续任务插队。"""

    now = datetime.now(UTC)
    item = await db.scalar(
        select(HostActionQueueItem)
        .where(
            HostActionQueueItem.room_id == room_id,
            HostActionQueueItem.status.in_(("queued", "processing", "retryable_failure")),
        )
        .order_by(HostActionQueueItem.position.asc())
        .limit(1)
    )
    if item is None:
        return None
    if item.status == "retryable_failure" and _utc(item.next_attempt_at) > now:
        return None
    if item.status == "processing" and _utc(item.lease_expires_at) > now:
        return None
    return item


async def mark_started(db: AsyncSession, item: HostActionQueueItem) -> None:
    """Keeper 已接管队列项；旧 started 语义在新状态机中对应 completed。"""

    item.status = "completed"
    item.lease_owner = None
    item.lease_expires_at = None
    item.next_attempt_at = None
    item.updated_at = datetime.now(UTC)
    await db.commit()


async def save_execution_route(
    db: AsyncSession,
    item: HostActionQueueItem,
    *,
    route: Literal["direct_response", "delegate_to_legacy"],
    text: str | None,
    provenance: str,
) -> None:
    """Durably freeze the A1 decision before executing the selected route."""

    item.execution_route = route
    item.direct_response_text = text
    item.execution_provenance = provenance
    await db.commit()


def effective_execution_route(
    item: HostActionQueueItem,
) -> Literal["direct_response", "delegate_to_legacy", "unresolved"]:
    """Pre-A migrations left the column NULL; those records belong to legacy."""

    if item.execution_route in {"direct_response", "delegate_to_legacy", "unresolved"}:
        return cast(
            Literal["direct_response", "delegate_to_legacy", "unresolved"],
            item.execution_route,
        )
    return "delegate_to_legacy"


async def mark_completed_with_events(
    db: AsyncSession,
    item: HostActionQueueItem,
    event_ids: list[str],
) -> None:
    item.result_event_ids = list(event_ids)
    item.status = "completed"
    item.lease_owner = None
    item.lease_expires_at = None
    item.next_attempt_at = None
    item.updated_at = datetime.now(UTC)
    await db.commit()


async def claim_npc(
    db: AsyncSession,
    item: HostActionQueueItem,
    *,
    lease_seconds: int = 180,
) -> HostActionQueueItem | None:
    """Compatibility wrapper for the generalized atomic claim."""
    return await claim(
        db,
        item,
        recipient_kind="npc",
        lease_seconds=lease_seconds,
    )


async def claim(
    db: AsyncSession,
    item: HostActionQueueItem,
    *,
    recipient_kind: Literal["keeper", "npc"] | None = None,
    lease_seconds: int = 180,
) -> HostActionQueueItem | None:
    """Conditionally claim the FIFO item for either keeper or NPC execution."""

    now = datetime.now(UTC)
    owner = str(uuid.uuid4())
    room_id = item.room_id
    item_id = item.item_id
    eligible = or_(
        HostActionQueueItem.status == "queued",
        and_(
            HostActionQueueItem.status == "retryable_failure",
            or_(
                HostActionQueueItem.next_attempt_at.is_(None),
                HostActionQueueItem.next_attempt_at <= now,
            ),
        ),
        and_(
            HostActionQueueItem.status == "processing",
            HostActionQueueItem.lease_expires_at <= now,
        ),
    )
    result = await db.execute(
        update(HostActionQueueItem)
        .where(
            HostActionQueueItem.room_id == room_id,
            HostActionQueueItem.item_id == item_id,
            *([HostActionQueueItem.recipient_kind == recipient_kind] if recipient_kind else []),
            eligible,
        )
        .values(
            status="processing",
            lease_owner=owner,
            lease_expires_at=now + timedelta(seconds=max(180, lease_seconds)),
            attempt_count=HostActionQueueItem.attempt_count + 1,
            next_attempt_at=None,
            updated_at=now,
        )
        .returning(HostActionQueueItem.item_id)
        # SQLite round-trips timezone-aware columns as naive UTC.  Evaluating the
        # WHERE in Python then TypeErrors (aware vs naive) and aborts a valid SQL
        # claim.  Expire the local row and reload it after commit instead.
        .execution_options(synchronize_session=False)
    )
    claimed_item_id = result.scalar_one_or_none()
    db.expire(item)
    await db.commit()
    if claimed_item_id is None:
        return None
    return await db.scalar(
        select(HostActionQueueItem).where(
            HostActionQueueItem.room_id == room_id,
            HostActionQueueItem.item_id == item_id,
            HostActionQueueItem.lease_owner == owner,
        )
    )


async def mark_npc_retryable(
    db: AsyncSession,
    item: HostActionQueueItem,
    *,
    delay_seconds: int = 5,
) -> None:
    """保留已经落库的玩家发言，释放 lease 并安排唯一一次队列级重试。"""

    now = datetime.now(UTC)
    item.status = "retryable_failure"
    item.next_attempt_at = now + timedelta(seconds=delay_seconds)
    item.lease_owner = None
    item.lease_expires_at = None
    item.updated_at = now
    await db.commit()


async def mark_npc_failed(db: AsyncSession, item: HostActionQueueItem) -> None:
    """将不可恢复的 NPC 请求置为终态，并释放房间行动槽。"""

    item.status = "failed"
    item.next_attempt_at = None
    item.lease_owner = None
    item.lease_expires_at = None
    item.updated_at = datetime.now(UTC)
    await db.commit()


async def discard(db: AsyncSession, item: HostActionQueueItem) -> None:
    item.status = "discarded"
    item.lease_owner = None
    item.lease_expires_at = None
    item.next_attempt_at = None
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


def _utc(value: datetime | None) -> datetime:
    """SQLite 可能返回无时区时间；统一为 UTC 后再计算恢复延迟。"""

    if value is None:
        return datetime.min.replace(tzinfo=UTC)
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


async def recovery_schedule(db: AsyncSession) -> tuple[tuple[str, float], ...]:
    """按每个房间 FIFO 队首计算启动恢复时间，避免轮询和任务越序。"""

    rows = (
        await db.scalars(
            select(HostActionQueueItem)
            .where(
                HostActionQueueItem.status.in_(("queued", "processing", "retryable_failure")),
            )
            .order_by(HostActionQueueItem.room_id, HostActionQueueItem.position)
        )
    ).all()
    now = datetime.now(UTC)
    result: list[tuple[str, float]] = []
    seen_rooms: set[str] = set()
    for item in rows:
        if item.room_id in seen_rooms:
            continue
        seen_rooms.add(item.room_id)
        ready_at = now
        if item.status == "retryable_failure":
            ready_at = _utc(item.next_attempt_at)
        elif item.status == "processing":
            ready_at = _utc(item.lease_expires_at)
        result.append((item.room_id, max(0.0, (ready_at - now).total_seconds())))
    return tuple(result)
