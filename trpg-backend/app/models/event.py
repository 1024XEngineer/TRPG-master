"""事件日志 ORM 模型（issue #77 §1，只增不改的 2 张表）。

- Event：房间内发生的所有事件的统一流水（叙事推送/玩家行动/未来的检定等），
  `GET /rooms/{roomId}/replay` 直接顺序读这张表——是本期唯一一条"服务端真的
  在写、也真的在读"的事件日志闭环（ws.py 在 narration.push / action.submit
  时插入行）。
- CheckResult：检定结果记录（技能检定/理智检定），本期 `check.roll`/
  `san.check.roll` 走 NOT_IMPLEMENTED 桩，不会真的写入这张表，只铺表结构。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("rooms.id"), nullable=False
    )
    player_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("players.id"), nullable=True
    )
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class CheckResult(Base):
    __tablename__ = "check_results"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("rooms.id"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("players.id"), nullable=False
    )
    character_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("characters.id"), nullable=True
    )
    check_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "skill" | "san"
    skill_or_stat: Mapped[str | None] = mapped_column(String(100), nullable=True)
    roll_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
