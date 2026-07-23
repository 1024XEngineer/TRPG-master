"""复盘与导入 ORM 模型（issue #77 §1）。

两张表都还没有真实的写入路径：复盘摘要依赖 AI 编排生成内容（归 #48/#68），
模组导入依赖真实 LLM 解析管线（归 #57），本期只铺表 + 接口，读写均返回
`NOT_IMPLEMENTED`。原 ``room_sessions`` 已由规则引擎权威且与 Room 一对一的
``game_sessions`` 替代；一个 Room 不支持开启第二局。
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid
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
