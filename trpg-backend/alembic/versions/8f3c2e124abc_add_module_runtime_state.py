"""add ModulePackage revisions and authoritative game runtime state

Revision ID: 8f3c2e124abc
Revises: 1a02058345ee
Create Date: 2026-07-23
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8f3c2e124abc"
down_revision: str | Sequence[str] | None = "1a02058345ee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scenario_revisions",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("scenario_id", sa.Uuid(), nullable=False),
        sa.Column("package_id", sa.String(length=255), nullable=False),
        sa.Column("schema_version", sa.String(length=20), nullable=False),
        sa.Column("checksum", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("rights_status", sa.String(length=30), nullable=False),
        sa.Column("package_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["scenario_id"], ["scenarios.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "scenario_id", "checksum", name="uq_scenario_revisions_checksum"
        ),
    )
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.add_column(sa.Column("current_revision_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_scenarios_current_revision",
            "scenario_revisions",
            ["current_revision_id"],
            ["id"],
        )

    with op.batch_alter_table("module_pregens") as batch_op:
        batch_op.add_column(sa.Column("revision_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("source_character_id", sa.String(length=255), nullable=True))
        batch_op.create_foreign_key(
            "fk_module_pregens_revision", "scenario_revisions", ["revision_id"], ["id"]
        )

    with op.batch_alter_table("room_sessions") as batch_op:
        batch_op.add_column(sa.Column("scenario_revision_id", sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(
            "fk_room_sessions_scenario_revision",
            "scenario_revisions",
            ["scenario_revision_id"],
            ["id"],
        )

    op.create_table(
        "game_state_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_session_id", sa.Uuid(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["room_session_id"], ["room_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_session_id"),
    )
    op.create_table(
        "processed_commands",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_session_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("request_hash", sa.String(length=64), nullable=False),
        sa.Column("result", sa.JSON(), nullable=False),
        sa.Column("state_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["room_session_id"], ["room_sessions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "room_session_id", "request_id", name="uq_processed_command_request"
        ),
    )
    op.create_table(
        "agent_sessions",
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.PrimaryKeyConstraint("session_id"),
    )
    op.create_table(
        "agent_messages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("session_id", sa.String(), nullable=False),
        sa.Column("message_data", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.ForeignKeyConstraint(
            ["session_id"], ["agent_sessions.session_id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_agent_messages_session_time",
        "agent_messages",
        ["session_id", "created_at"],
        unique=False,
    )

    with op.batch_alter_table("events") as batch_op:
        batch_op.add_column(sa.Column("room_session_id", sa.Uuid(), nullable=True))
        batch_op.add_column(sa.Column("sequence", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("request_id", sa.String(length=100), nullable=True))
        batch_op.add_column(
            sa.Column(
                "visibility",
                sa.String(length=20),
                nullable=False,
                server_default="room",
            )
        )
        batch_op.add_column(sa.Column("state_revision", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_events_room_session", "room_sessions", ["room_session_id"], ["id"]
        )
        batch_op.create_unique_constraint(
            "uq_events_session_sequence", ["room_session_id", "sequence"]
        )

    with op.batch_alter_table("check_results") as batch_op:
        batch_op.add_column(sa.Column("checkpoint_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("sanity_event_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("request_id", sa.String(length=100), nullable=True))

    with op.batch_alter_table("room_summaries") as batch_op:
        batch_op.add_column(sa.Column("ending_id", sa.String(length=255), nullable=True))
        batch_op.add_column(sa.Column("outcome", sa.String(length=100), nullable=True))
        batch_op.add_column(sa.Column("structured_data", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("room_summaries") as batch_op:
        batch_op.drop_column("structured_data")
        batch_op.drop_column("outcome")
        batch_op.drop_column("ending_id")
    with op.batch_alter_table("check_results") as batch_op:
        batch_op.drop_column("request_id")
        batch_op.drop_column("sanity_event_id")
        batch_op.drop_column("checkpoint_id")
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_constraint("uq_events_session_sequence", type_="unique")
        batch_op.drop_constraint("fk_events_room_session", type_="foreignkey")
        batch_op.drop_column("state_revision")
        batch_op.drop_column("visibility")
        batch_op.drop_column("request_id")
        batch_op.drop_column("sequence")
        batch_op.drop_column("room_session_id")
    op.drop_index("idx_agent_messages_session_time", table_name="agent_messages")
    op.drop_table("agent_messages")
    op.drop_table("agent_sessions")
    op.drop_table("processed_commands")
    op.drop_table("game_state_snapshots")
    with op.batch_alter_table("room_sessions") as batch_op:
        batch_op.drop_constraint("fk_room_sessions_scenario_revision", type_="foreignkey")
        batch_op.drop_column("scenario_revision_id")
    with op.batch_alter_table("module_pregens") as batch_op:
        batch_op.drop_constraint("fk_module_pregens_revision", type_="foreignkey")
        batch_op.drop_column("source_character_id")
        batch_op.drop_column("revision_id")
    with op.batch_alter_table("scenarios") as batch_op:
        batch_op.drop_constraint("fk_scenarios_current_revision", type_="foreignkey")
        batch_op.drop_column("current_revision_id")
    op.drop_table("scenario_revisions")
