"""事件日志 ORM 模型（issue #77 §1、issue #89，只增不改的 2 张表）。

- Event：传输、叙事和回放流水（叙事推送/未来的检定等），
  `GET /rooms/{roomId}/replay` 直接顺序读这张表。它不是规则引擎的权威
  Event，不参与 GameState 重建，也不提供规则动作幂等；规则引擎状态变化
  单独保存在 ``game_events``。可空的 ``correlation_id`` 为动作产生的叙事
  提供持久化去重键，旧 ``events`` 不再记录 ``action.submit``。
- CheckResult：检定结果记录（技能检定/理智检定），本期 `check.roll`/
  `san.check.roll` 走 NOT_IMPLEMENTED 桩，不会真的写入这张表，只铺表结构。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint(
            "room_id",
            "event_type",
            "correlation_id",
            name="uq_events_room_type_correlation",
        ),
        CheckConstraint(
            "visibility IN ('public', 'player_scoped', 'scene_scoped')",
            name="ck_events_visibility",
        ),
        CheckConstraint(
            "visibility != 'player_scoped' OR player_id IS NOT NULL",
            name="ck_events_player_scoped_owner",
        ),
        Index("ix_events_room_created", "room_id", "created_at"),
        Index(
            "ix_events_room_visibility_player_created",
            "room_id",
            "visibility",
            "player_id",
            "created_at",
        ),
    )

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
    correlation_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    visibility: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="public",
    )
    actor_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scene_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    view_revision: Mapped[str | None] = mapped_column(String(200), nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class EventAudience(Base):
    """冻结场景事件发生时有权接收和回放该事件的玩家。"""

    __tablename__ = "event_audiences"
    __table_args__ = (
        PrimaryKeyConstraint("event_id", "player_id", name="pk_event_audiences"),
        Index("ix_event_audiences_player_event", "player_id", "event_id"),
    )

    event_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("events.id", ondelete="CASCADE"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("players.id", ondelete="CASCADE"), nullable=False
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
