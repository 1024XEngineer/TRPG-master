"""规则引擎权威持久化基础模型（issue #89）。

本模块只定义数据库结构，不实现 EngineStore、开局流程或 WebSocket 接入：

- ``ModuleVersion`` 保存经过 ``ModuleContent`` 校验的不可变发布内容；
- ``GameSession`` 保存一个 Room 唯一的权威 ``GameState``；
- ``GameEvent`` 保存规则引擎只追加的状态变化事件；
- ``ActionExecution`` 保存动作请求与首次执行结果，用于后续幂等重放。

所有领域对象使用 SQLAlchemy 通用 ``JSON``，保持 SQLite 与 PostgreSQL 一致。
"""

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class ModuleVersion(Base):
    """一个 Scenario 的不可变、完整且已经校验的发布版本。"""

    __tablename__ = "module_versions"
    __table_args__ = (
        PrimaryKeyConstraint("module_id", "version", name="pk_module_versions"),
        CheckConstraint(
            "content_schema_version >= 1",
            name="ck_module_versions_content_schema_version",
        ),
    )

    module_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("scenarios.id"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    world_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    content_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    content_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class GameSession(Base):
    """一个 Room 唯一的一局游戏及其当前权威 GameState。"""

    __tablename__ = "game_sessions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["module_id", "module_version"],
            ["module_versions.module_id", "module_versions.version"],
            name="fk_game_sessions_module_version",
        ),
        CheckConstraint(
            "state_schema_version >= 1",
            name="ck_game_sessions_state_schema_version",
        ),
        CheckConstraint("state_version >= 0", name="ck_game_sessions_state_version"),
    )

    # room_id 同时是主键和外键，从数据库层保证一个 Room 只能运行一局。
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("rooms.id"), primary_key=True
    )
    module_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), nullable=False)
    module_version: Mapped[str] = mapped_column(String(50), nullable=False)
    state_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    state_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class GameEvent(Base):
    """规则引擎产生的权威、只追加状态变化 Event。"""

    __tablename__ = "game_events"
    __table_args__ = (
        PrimaryKeyConstraint("room_id", "sequence", name="pk_game_events"),
        UniqueConstraint("room_id", "event_id", name="uq_game_events_room_event"),
        CheckConstraint("sequence >= 1", name="ck_game_events_sequence"),
        CheckConstraint(
            "event_schema_version >= 1",
            name="ck_game_events_event_schema_version",
        ),
        CheckConstraint(
            "visibility IN ('public', 'private', 'hidden')",
            name="ck_game_events_visibility",
        ),
        Index(
            "ix_game_events_room_client_action",
            "room_id",
            "client_action_id",
        ),
    )

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(BigInteger, nullable=False)
    event_id: Mapped[str] = mapped_column(String(100), nullable=False)
    client_action_id: Mapped[str] = mapped_column(String(200), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    visibility: Mapped[str] = mapped_column(String(20), nullable=False)
    cause: Mapped[str] = mapped_column(Text, nullable=False)
    event_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class ActionExecution(Base):
    """首次动作请求和完整执行结果的持久化幂等记录。"""

    __tablename__ = "action_executions"
    __table_args__ = (
        PrimaryKeyConstraint("room_id", "request_id", name="pk_action_executions"),
        CheckConstraint(
            "request_schema_version >= 1",
            name="ck_action_executions_request_schema_version",
        ),
        CheckConstraint(
            "result_schema_version >= 1",
            name="ck_action_executions_result_schema_version",
        ),
        CheckConstraint(
            "committed_state_version >= 0",
            name="ck_action_executions_committed_state_version",
        ),
    )

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    request_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    committed_state_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
