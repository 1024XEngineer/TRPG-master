"""add durable adjudication check workflow

Revision ID: a212b3c4d5e6
Revises: e4b6c8d0f2a1
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a212b3c4d5e6"
down_revision: str | Sequence[str] | None = "e4b6c8d0f2a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pending_check_decisions",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("decision_id", sa.String(length=100), nullable=False),
        sa.Column("action_request_id", sa.String(length=200), nullable=False),
        sa.Column("player_id", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("decision_version", sa.Integer(), nullable=False),
        sa.Column(
            "decision_schema_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("decision_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision_version >= 1",
            name="ck_pending_check_decision_version",
        ),
        sa.CheckConstraint(
            "decision_schema_version >= 1",
            name="ck_pending_check_decision_schema_version",
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_skill_choice', 'rolled', 'resolved', 'cancelled')",
            name="ck_pending_check_decision_status",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint(
            "room_id",
            "decision_id",
            name="pk_pending_check_decisions",
        ),
        sa.UniqueConstraint(
            "room_id",
            "action_request_id",
            name="uq_pending_check_decisions_room_action",
        ),
    )
    op.create_table(
        "check_runs",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("check_id", sa.String(length=100), nullable=False),
        sa.Column("decision_id", sa.String(length=100), nullable=False),
        sa.Column("action_request_id", sa.String(length=200), nullable=False),
        sa.Column("player_id", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("roll_count", sa.Integer(), nullable=False),
        sa.Column(
            "check_schema_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("check_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_check_runs_version"),
        sa.CheckConstraint(
            "check_schema_version >= 1",
            name="ck_check_runs_schema_version",
        ),
        sa.CheckConstraint(
            "roll_count BETWEEN 1 AND 2",
            name="ck_check_runs_roll_count",
        ),
        sa.CheckConstraint(
            "status IN ('awaiting_post_roll_decision', 'resolved')",
            name="ck_check_runs_status",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.ForeignKeyConstraint(
            ["room_id", "decision_id"],
            [
                "pending_check_decisions.room_id",
                "pending_check_decisions.decision_id",
            ],
            name="fk_check_runs_pending_decision",
        ),
        sa.PrimaryKeyConstraint("room_id", "check_id", name="pk_check_runs"),
        sa.UniqueConstraint(
            "room_id",
            "decision_id",
            name="uq_check_runs_room_decision",
        ),
    )
    op.create_table(
        "adjudication_command_executions",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column(
            "request_schema_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column(
            "result_schema_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("committed_state_version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "committed_state_version >= 0",
            name="ck_adjudication_commands_state_version",
        ),
        sa.CheckConstraint(
            "request_schema_version >= 1",
            name="ck_adjudication_commands_request_schema_version",
        ),
        sa.CheckConstraint(
            "result_schema_version >= 1",
            name="ck_adjudication_commands_result_schema_version",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint(
            "room_id",
            "request_id",
            name="pk_adjudication_command_executions",
        ),
    )


def downgrade() -> None:
    op.drop_table("adjudication_command_executions")
    op.drop_table("check_runs")
    op.drop_table("pending_check_decisions")
