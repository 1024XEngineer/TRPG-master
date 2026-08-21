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
    Boolean,
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
            "content_schema_version = 3",
            name="ck_module_versions_content_schema_version",
        ),
    )

    module_id: Mapped[str] = mapped_column(
        String(200), ForeignKey("scenarios.module_id"), nullable=False
    )
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    world_ref: Mapped[str] = mapped_column(String(200), nullable=False)
    content_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
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
        CheckConstraint(
            "agenda_state_version >= 0",
            name="ck_game_sessions_agenda_state_version",
        ),
    )

    # room_id 同时是主键和外键，从数据库层保证一个 Room 只能运行一局。
    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("rooms.id"), primary_key=True
    )
    module_id: Mapped[str] = mapped_column(String(200), nullable=False)
    module_version: Mapped[str] = mapped_column(String(50), nullable=False)
    state_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    state_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    state_version: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    agenda_state_version: Mapped[int] = mapped_column(
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


class TimeAdvanceProposalRecord(Base):
    """多人房间推进共享世界时间时使用的持久化全员确认提案。"""

    __tablename__ = "time_advance_proposals"
    __table_args__ = (
        PrimaryKeyConstraint("room_id", "proposal_id", name="pk_time_advance_proposals"),
        CheckConstraint("proposal_version >= 1", name="ck_time_advance_proposal_version"),
        CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'stale')",
            name="ck_time_advance_proposal_status",
        ),
        Index(
            "ix_time_advance_proposals_room_status",
            "room_id",
            "status",
            "updated_at",
        ),
    )

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    proposal_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_revision: Mapped[int] = mapped_column(BigInteger, nullable=False)
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    player_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action_request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    # 单动作直接等于 action_request_id；ActionPlan 在返回等待态时会绑定到
    # 父行动 ID，最终确认后据此恢复整条原计划，而不是把步骤 ID 当作计划 ID。
    parent_action_id: Mapped[str] = mapped_column(String(200), nullable=False)
    requester_player_id: Mapped[str] = mapped_column(String(100), nullable=False)
    target_point_id: Mapped[str] = mapped_column(String(100), nullable=False)
    target_day_index: Mapped[int] = mapped_column(Integer, nullable=False)
    target_hour_of_day: Mapped[int] = mapped_column(Integer, nullable=False)
    required_player_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    accepted_player_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    # 冻结 Agent 已产生的原裁决与应用层等待状态，不在最后一票时重新
    # 调用模型。两者均由强类型 Contract 序列化，读取时必须再校验。
    adjudication_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    execution_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    committed_revision: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    narration_persisted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
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


class PendingCheckDecisionRecord(Base):
    """Durable, player-owned pre-roll choice with the full adjudication frozen."""

    __tablename__ = "pending_check_decisions"
    __table_args__ = (
        PrimaryKeyConstraint("room_id", "decision_id", name="pk_pending_check_decisions"),
        UniqueConstraint(
            "room_id",
            "action_request_id",
            name="uq_pending_check_decisions_room_action",
        ),
        CheckConstraint("decision_version >= 1", name="ck_pending_check_decision_version"),
        CheckConstraint(
            "decision_schema_version >= 1",
            name="ck_pending_check_decision_schema_version",
        ),
        CheckConstraint(
            "status IN ('awaiting_skill_choice', 'rolled', 'resolved', 'cancelled')",
            name="ck_pending_check_decision_status",
        ),
    )

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    decision_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action_request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    player_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    decision_version: Mapped[int] = mapped_column(Integer, nullable=False)
    decision_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    decision_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class CheckRunRecord(Base):
    """A server-authoritative roll and its optional post-roll decision state."""

    __tablename__ = "check_runs"
    __table_args__ = (
        PrimaryKeyConstraint("room_id", "check_id", name="pk_check_runs"),
        ForeignKeyConstraint(
            ["room_id", "decision_id"],
            [
                "pending_check_decisions.room_id",
                "pending_check_decisions.decision_id",
            ],
            name="fk_check_runs_pending_decision",
        ),
        UniqueConstraint("room_id", "decision_id", name="uq_check_runs_room_decision"),
        CheckConstraint("version >= 1", name="ck_check_runs_version"),
        CheckConstraint(
            "check_schema_version >= 1",
            name="ck_check_runs_schema_version",
        ),
        CheckConstraint("roll_count BETWEEN 1 AND 2", name="ck_check_runs_roll_count"),
        CheckConstraint(
            "status IN ('awaiting_post_roll_decision', 'resolved')",
            name="ck_check_runs_status",
        ),
    )

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    check_id: Mapped[str] = mapped_column(String(100), nullable=False)
    decision_id: Mapped[str] = mapped_column(String(100), nullable=False)
    action_request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    player_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    roll_count: Mapped[int] = mapped_column(Integer, nullable=False)
    check_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    check_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class AdjudicationCommandExecution(Base):
    """Idempotency record for submit, skill choice, cancel, luck and push commands."""

    __tablename__ = "adjudication_command_executions"
    __table_args__ = (
        PrimaryKeyConstraint(
            "room_id",
            "request_id",
            name="pk_adjudication_command_executions",
        ),
        CheckConstraint(
            "committed_state_version >= 0",
            name="ck_adjudication_commands_state_version",
        ),
        CheckConstraint(
            "request_schema_version >= 1",
            name="ck_adjudication_commands_request_schema_version",
        ),
        CheckConstraint(
            "result_schema_version >= 1",
            name="ck_adjudication_commands_result_schema_version",
        ),
        Index(
            "ix_adjudication_commands_room_action",
            "room_id",
            "action_request_id",
            "committed_state_version",
        ),
    )

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    action_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
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


class ActionPlanRunRecord(Base):
    """A-owned orchestration cursor persisted separately from Engine commands."""

    __tablename__ = "action_plan_runs"
    __table_args__ = (
        PrimaryKeyConstraint(
            "room_id",
            "parent_action_id",
            name="pk_action_plan_runs",
        ),
        UniqueConstraint("plan_id", name="uq_action_plan_runs_plan_id"),
        CheckConstraint("run_version >= 1", name="ck_action_plan_runs_version"),
        CheckConstraint(
            "plan_schema_version >= 1",
            name="ck_action_plan_runs_schema_version",
        ),
        CheckConstraint(
            "status IN ('active', 'checkpointed', 'waiting_for_player', "
            "'awaiting_time_consent', "
            "'needs_clarification', 'retryable_failure', 'awaiting_narration', "
            "'completed', 'cancelled', 'stopped')",
            name="ck_action_plan_runs_status",
        ),
        Index("ix_action_plan_runs_room_status", "room_id", "status"),
    )

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    parent_action_id: Mapped[str] = mapped_column(String(200), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(100), nullable=False)
    parent_input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    player_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False)
    current_step_index: Mapped[int] = mapped_column(Integer, nullable=False)
    run_version: Mapped[int] = mapped_column(Integer, nullable=False)
    plan_schema_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    run_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    lease_owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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


class RoomActionReservation(Base):
    """One durable active parent action owner per room."""

    __tablename__ = "room_action_reservations"
    __table_args__ = (
        ForeignKeyConstraint(
            ["room_id", "parent_action_id"],
            ["action_plan_runs.room_id", "action_plan_runs.parent_action_id"],
            name="fk_room_action_reservation_plan",
            ondelete="CASCADE",
        ),
        UniqueConstraint("plan_id", name="uq_room_action_reservations_plan"),
    )

    room_id: Mapped[str] = mapped_column(Uuid(as_uuid=False), primary_key=True)
    parent_action_id: Mapped[str] = mapped_column(String(200), nullable=False)
    plan_id: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class InventoryImportDraftRecord(Base):
    """Reviewable character-sheet item import before it mutates room state."""

    __tablename__ = "inventory_import_drafts"
    __table_args__ = (
        PrimaryKeyConstraint("room_id", "draft_id", name="pk_inventory_import_drafts"),
        UniqueConstraint("room_id", "request_id", name="uq_inventory_import_drafts_request"),
        CheckConstraint("version >= 1", name="ck_inventory_import_draft_version"),
    )

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    draft_id: Mapped[str] = mapped_column(String(100), nullable=False)
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    player_id: Mapped[str] = mapped_column(String(100), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    confirmed: Mapped[bool] = mapped_column(nullable=False, default=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    draft_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class InventoryCommandExecution(Base):
    """Durable idempotency record for import confirmation and custody CAS."""

    __tablename__ = "inventory_command_executions"
    __table_args__ = (
        PrimaryKeyConstraint("room_id", "request_id", name="pk_inventory_command_executions"),
        CheckConstraint(
            "committed_state_version >= 0",
            name="ck_inventory_command_state_version",
        ),
    )

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    committed_state_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )


class EndingDraftRecord(Base):
    """Grounded, revision-bound ending text awaiting explicit confirmation."""

    __tablename__ = "ending_drafts"
    __table_args__ = (
        PrimaryKeyConstraint("room_id", "draft_id", name="pk_ending_drafts"),
        UniqueConstraint("room_id", "request_id", name="uq_ending_drafts_request"),
        CheckConstraint("version >= 1", name="ck_ending_draft_version"),
        CheckConstraint(
            "status IN ('active', 'confirmed', 'expired')",
            name="ck_ending_draft_status",
        ),
    )

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    draft_id: Mapped[str] = mapped_column(String(100), nullable=False)
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    player_id: Mapped[str] = mapped_column(String(100), nullable=False)
    anchor_id: Mapped[str] = mapped_column(String(100), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    draft_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
    )


class EndingCommandExecution(Base):
    """Idempotency record for irreversible EndingDraft confirmation."""

    __tablename__ = "ending_command_executions"
    __table_args__ = (
        PrimaryKeyConstraint("room_id", "request_id", name="pk_ending_command_executions"),
        CheckConstraint(
            "committed_state_version >= 0",
            name="ck_ending_command_state_version",
        ),
    )

    room_id: Mapped[str] = mapped_column(
        Uuid(as_uuid=False), ForeignKey("game_sessions.room_id"), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(200), nullable=False)
    request_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    result_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    committed_state_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
