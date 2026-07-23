"""房间会话、权威状态、复盘与模组导入 ORM 模型。

`room_sessions` 将每局游戏固定绑定到不可变的 ScenarioRevision；
`game_state_snapshots` 保存版本化权威状态，`processed_commands` 提供命令幂等。
模组导入任务仍属于独立解析管线，本文件只保留其已有表结构。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class RoomSummary(Base):
    __tablename__ = "room_summaries"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("rooms.id"), unique=True, nullable=False
    )
    summary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    highlights: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    ending_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    outcome: Mapped[str | None] = mapped_column(String(100), nullable=True)
    structured_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class RoomSession(Base):
    __tablename__ = "room_sessions"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("rooms.id"), nullable=False
    )
    scenario_revision_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenario_revisions.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class GameStateSnapshot(Base):
    """一局游戏的当前权威状态；历史变化写入 EventLog。"""

    __tablename__ = "game_state_snapshots"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_session_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("room_sessions.id"), unique=True, nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    state: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class ProcessedCommand(Base):
    """客户端命令幂等记录：同 request_id 只能对应同一份输入。"""

    __tablename__ = "processed_commands"
    __table_args__ = (
        UniqueConstraint("room_session_id", "request_id", name="uq_processed_command_request"),
    )

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    room_session_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("room_sessions.id"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    result: Mapped[dict] = mapped_column(JSON, nullable=False)
    state_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class ModuleImportJob(Base):
    __tablename__ = "module_import_jobs"

    id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    source_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    result_scenario_id: Mapped[str | None] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenarios.id"), nullable=True
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )
