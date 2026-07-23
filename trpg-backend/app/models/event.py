"""事件日志与权威检定结果 ORM 模型。

- Event：一局内发生的叙事、行动、检定、线索和结局等统一流水。
- CheckResult：由服务端生成的技能检定与理智检定结果。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class Event(Base):
    __tablename__ = "events"
    __table_args__ = (
        UniqueConstraint("room_session_id", "sequence", name="uq_events_session_sequence"),
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
    room_session_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("room_sessions.id"), nullable=True
    )
    sequence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="room")
    state_revision: Mapped[int | None] = mapped_column(Integer, nullable=True)
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
    checkpoint_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    sanity_event_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    roll_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    target_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
