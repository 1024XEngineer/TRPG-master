"""长期记忆与玩家独立对话摘要的可重建数据库投影。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
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
        Index("ix_memory_entries_room_source_created", "room_id", "source_created_at"),
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
    # 冻结受众是玩家权限；scene_scoped 的空受众不能视为公开。
    audience_player_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    location_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    source_revision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 两类来源事件的 sequence 不可直接比较，统一用真实发生时间决定同级记忆的新旧。
    source_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class MemoryProjectionCursor(Base):
    """记录房间两类事件流的投影高水位，避免每次读取都重放全量历史。"""

    __tablename__ = "memory_projection_cursors"

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), primary_key=True
    )
    event_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    event_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    game_sequence: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    projection_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class MemoryProjectionReceipt(Base):
    """逐条记录已处理来源，包括无正文事件，不依赖事件的提交顺序。"""

    __tablename__ = "memory_projection_receipts"

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), primary_key=True
    )
    source_kind: Mapped[str] = mapped_column(String(10), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(100), primary_key=True)


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
    projection_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 摘要游标使用 Event 的真实发生时间和稳定 ID，避免不同事件流的 sequence 混比。
    through_event_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    through_event_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pending_event_created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    pending_event_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 旧字段保留给历史客户端和摘要 DTO；新的查询不再用它比较事件新旧。
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


class ConversationSummaryReceipt(Base):
    """每个玩家摘要消费过的事件与正文位置，晚提交事件及长文本可继续处理。"""

    __tablename__ = "conversation_summary_receipts"

    summary_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False),
        ForeignKey("conversation_summaries.id", ondelete="CASCADE"),
        primary_key=True,
    )
    event_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("events.id", ondelete="CASCADE"), primary_key=True
    )
    consumed_chars: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    complete: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
