"""Align database module identity with ModuleContent v1.

Revision ID: b7e4c2d1a6f9
Revises: 9c4e7a2b1d6f
Create Date: 2026-07-25 16:30:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b7e4c2d1a6f9"
down_revision: str | Sequence[str] | None = "9c4e7a2b1d6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _guard_existing_data() -> None:
    """本期不迁移历史目录或运行时数据，任何相关数据都必须显式拒绝。"""

    connection = op.get_bind()
    for table_name in (
        "action_executions",
        "game_events",
        "game_sessions",
        "module_versions",
        "scenarios",
        "game_systems",
    ):
        if connection.execute(sa.text(f"SELECT 1 FROM {table_name} LIMIT 1")).first():
            raise RuntimeError(
                f"迁移已中止：{table_name} 存在历史数据；"
                "Issue #141 不处理历史数据兼容，请重建本地数据库。"
            )


def _drop_engine_tables() -> None:
    op.drop_table("action_executions")
    op.drop_index("ix_game_events_room_client_action", table_name="game_events")
    op.drop_table("game_events")
    op.drop_table("game_sessions")
    op.drop_table("module_versions")


def _create_engine_tables(*, stable_module_identity: bool) -> None:
    module_id_type = sa.String(length=200) if stable_module_identity else sa.Uuid(as_uuid=False)
    scenario_target = "scenarios.module_id" if stable_module_identity else "scenarios.id"

    op.create_table(
        "module_versions",
        sa.Column("module_id", module_id_type, nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("world_ref", sa.String(length=200), nullable=False),
        sa.Column(
            "content_schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("content_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "content_schema_version >= 1",
            name="ck_module_versions_content_schema_version",
        ),
        sa.ForeignKeyConstraint(
            ["module_id"],
            [scenario_target],
            name="fk_module_versions_scenario_module_id"
            if stable_module_identity
            else "fk_module_versions_scenario_id",
        ),
        sa.PrimaryKeyConstraint("module_id", "version", name="pk_module_versions"),
    )
    op.create_table(
        "game_sessions",
        sa.Column("room_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("module_id", module_id_type, nullable=False),
        sa.Column("module_version", sa.String(length=50), nullable=False),
        sa.Column(
            "state_schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("state_json", sa.JSON(), nullable=False),
        sa.Column(
            "state_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "state_schema_version >= 1",
            name="ck_game_sessions_state_schema_version",
        ),
        sa.CheckConstraint(
            "state_version >= 0",
            name="ck_game_sessions_state_version",
        ),
        sa.ForeignKeyConstraint(
            ["module_id", "module_version"],
            ["module_versions.module_id", "module_versions.version"],
            name="fk_game_sessions_module_version",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"]),
        sa.PrimaryKeyConstraint("room_id"),
    )
    op.create_table(
        "game_events",
        sa.Column("room_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column("event_id", sa.String(length=100), nullable=False),
        sa.Column("client_action_id", sa.String(length=200), nullable=False),
        sa.Column("type", sa.String(length=50), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("visibility", sa.String(length=20), nullable=False),
        sa.Column("cause", sa.Text(), nullable=False),
        sa.Column(
            "event_schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_game_events_sequence"),
        sa.CheckConstraint(
            "event_schema_version >= 1",
            name="ck_game_events_event_schema_version",
        ),
        sa.CheckConstraint(
            "visibility IN ('public', 'private', 'hidden')",
            name="ck_game_events_visibility",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("room_id", "sequence", name="pk_game_events"),
        sa.UniqueConstraint("room_id", "event_id", name="uq_game_events_room_event"),
    )
    op.create_index(
        "ix_game_events_room_client_action",
        "game_events",
        ["room_id", "client_action_id"],
        unique=False,
    )
    op.create_table(
        "action_executions",
        sa.Column("room_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column(
            "request_schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column(
            "result_schema_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("committed_state_version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "request_schema_version >= 1",
            name="ck_action_executions_request_schema_version",
        ),
        sa.CheckConstraint(
            "result_schema_version >= 1",
            name="ck_action_executions_result_schema_version",
        ),
        sa.CheckConstraint(
            "committed_state_version >= 0",
            name="ck_action_executions_committed_state_version",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("room_id", "request_id", name="pk_action_executions"),
    )


def upgrade() -> None:
    """增加稳定身份字段，并用字符串 module_id 重建空的运行时表。"""

    _guard_existing_data()
    _drop_engine_tables()

    op.add_column(
        "game_systems",
        sa.Column(
            "world_ref",
            sa.String(length=200),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    with op.batch_alter_table("game_systems") as batch_op:
        batch_op.alter_column(
            "world_ref",
            existing_type=sa.String(length=200),
            server_default=None,
        )
        batch_op.create_unique_constraint("uq_game_systems_world_ref", ["world_ref"])

    op.add_column(
        "scenarios",
        sa.Column(
            "module_id",
            sa.String(length=200),
            nullable=False,
            server_default=sa.text("''"),
        ),
    )
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.alter_column(
            "module_id",
            existing_type=sa.String(length=200),
            server_default=None,
        )
        batch_op.create_unique_constraint("uq_scenarios_module_id", ["module_id"])

    _create_engine_tables(stable_module_identity=True)


def downgrade() -> None:
    """恢复仅支持内部 UUID module_id 的空表结构。"""

    _guard_existing_data()
    _drop_engine_tables()

    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.drop_constraint("uq_scenarios_module_id", type_="unique")
        batch_op.drop_column("module_id")
    with op.batch_alter_table("game_systems") as batch_op:
        batch_op.drop_constraint("uq_game_systems_world_ref", type_="unique")
        batch_op.drop_column("world_ref")

    _create_engine_tables(stable_module_identity=False)
