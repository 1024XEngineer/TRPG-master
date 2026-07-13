"""EventLog —— 对应 master §4.5 `interface EventLog`。

实现上是 GameStateRepo 管辖范围内的一张表（events），接口单独列出是因为
调用方（EventLog 消费者：断线重连补发、复盘 GET /replay）跟 GameStateRepo
的调用方（RulesEngine/ViewProjector）不同。`append`/`list` 是 async——真实
实现要做真实数据库 I/O，同步接口会阻塞事件循环。

`list()` 的 `room_id` 是 2026-07-13 补的必填参数——原签名没有，见架构演进
日志同日条目：物理表一直有 room_id 列，逻辑接口却没暴露，真实实现无法
表达"查某个房间的事件"。
"""

from __future__ import annotations

from typing import Literal, Optional, Protocol, runtime_checkable

from sqlalchemy import select

from core.state.db_models import EventRow
from core.state.models import Event
from core.db import get_sessionmaker


@runtime_checkable
class EventLog(Protocol):
    async def append(self, event: Event) -> None:
        ...

    async def list(
        self,
        room_id: str,
        since_id: Optional[str] = None,
        visibility: Optional[Literal["public", "scene", "private"]] = None,
    ) -> list[Event]:
        """`visibility` 参数支持 §5.2.5 断线重连查询（重连只用 'public'）。"""
        ...


class StubEventLog:
    async def append(self, event: Event) -> None:
        raise NotImplementedError("EventLog.append: 待接入 PostgreSQL events 表")

    async def list(
        self,
        room_id: str,
        since_id: Optional[str] = None,
        visibility: Optional[Literal["public", "scene", "private"]] = None,
    ) -> list[Event]:
        raise NotImplementedError("EventLog.list: 待接入 PostgreSQL events 表")


class SqlAlchemyEventLog:
    """真实实现（ADR-17：PostgreSQL）。只增不改，见 master §4.4.5 迁移策略。"""

    async def append(self, event: Event) -> None:
        async with get_sessionmaker()() as session:
            session.add(
                EventRow(
                    id=event.id,
                    room_id=event.room_id,
                    player_id=event.player_id,
                    type=event.payload.type,
                    payload=event.payload.model_dump(by_alias=True),
                    visibility=event.visibility,
                    ts=event.ts,
                )
            )
            await session.commit()

    async def list(
        self,
        room_id: str,
        since_id: Optional[str] = None,
        visibility: Optional[Literal["public", "scene", "private"]] = None,
    ) -> list[Event]:
        async with get_sessionmaker()() as session:
            stmt = select(EventRow).where(EventRow.room_id == room_id)
            if since_id is not None:
                stmt = stmt.where(EventRow.id > since_id)
            if visibility is not None:
                stmt = stmt.where(EventRow.visibility == visibility)
            stmt = stmt.order_by(EventRow.id)

            rows = (await session.execute(stmt)).scalars().all()
            return [
                Event(
                    id=row.id,
                    room_id=row.room_id,
                    ts=row.ts,
                    player_id=row.player_id,
                    visibility=row.visibility,
                    payload=row.payload,
                )
                for row in rows
            ]
