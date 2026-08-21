"""长期记忆与玩家独立对话摘要的可重建数据库投影。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class MemoryEntryRecord(Base):
    """从权威事件确定性生成的一条玩家安全记忆。"""

    __tablename__ = "memory_entries"
    __table_args__ = (
        UniqueConstraint(
            "room_id",
            "subject_id",
            "source_event_id",
            "kind",
            name="uq_memory_entries_source",
        ),
        Index("ix_memory_entries_scope", "room_id", "subject_id", "visibility"),
        Index("ix_memory_entries_entity", "room_id", "object_id", "location_id"),
    )

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    subject_id: Mapped[str] = mapped_column(String(100), nullable=False)
    object_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    epistemic_status: Mapped[str] = mapped_column(String(30), nullable=False)
    visibility: Mapped[str] = mapped_column(String(30), nullable=False)
    participants: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # 与 participants 分开保存，避免把“共同参与”误当成“亲自听到”。
    listener_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    location_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ConversationSummaryRecord(Base):
    """每个房间/玩家一份摘要及其可恢复的异步任务状态。"""

    __tablename__ = "conversation_summaries"
    __table_args__ = (
        UniqueConstraint("room_id", "player_id", name="uq_conversation_summaries_scope"),
        Index("ix_conversation_summaries_tasks", "status", "next_attempt_at"),
    )

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    player_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("players.id"), nullable=False
    )
    summary_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    through_event_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pending_through_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    source_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="idle")
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_owner: Mapped[str | None] = mapped_column(String(100), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
