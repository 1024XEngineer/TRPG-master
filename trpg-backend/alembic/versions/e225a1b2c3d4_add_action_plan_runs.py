"""add durable finite action plan runs

Revision ID: e225a1b2c3d4
Revises: a212b3c4d5e6
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e225a1b2c3d4"
down_revision: str | Sequence[str] | None = "a212b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "adjudication_command_executions",
        sa.Column("action_request_id", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_adjudication_commands_room_action",
        "adjudication_command_executions",
        ["room_id", "action_request_id", "committed_state_version"],
        unique=False,
    )
    op.create_table(
        "action_plan_runs",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("parent_action_id", sa.String(length=200), nullable=False),
        sa.Column("plan_id", sa.String(length=100), nullable=False),
        sa.Column("parent_input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("player_id", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=40), nullable=False),
        sa.Column("current_step_index", sa.Integer(), nullable=False),
        sa.Column("run_version", sa.Integer(), nullable=False),
        sa.Column(
            "plan_schema_version",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
        sa.Column("run_json", sa.JSON(), nullable=False),
        sa.Column("lease_owner", sa.String(length=200), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("run_version >= 1", name="ck_action_plan_runs_version"),
        sa.CheckConstraint(
            "plan_schema_version >= 1",
            name="ck_action_plan_runs_schema_version",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'checkpointed', 'waiting_for_player', "
            "'needs_clarification', 'retryable_failure', 'awaiting_narration', "
            "'completed', 'cancelled', 'stopped')",
            name="ck_action_plan_runs_status",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint(
            "room_id",
            "parent_action_id",
            name="pk_action_plan_runs",
        ),
        sa.UniqueConstraint("plan_id", name="uq_action_plan_runs_plan_id"),
    )
    op.create_index(
        "ix_action_plan_runs_room_status",
        "action_plan_runs",
        ["room_id", "status"],
        unique=False,
    )
    op.create_table(
        "room_action_reservations",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("parent_action_id", sa.String(length=200), nullable=False),
        sa.Column("plan_id", sa.String(length=100), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["room_id", "parent_action_id"],
            ["action_plan_runs.room_id", "action_plan_runs.parent_action_id"],
            name="fk_room_action_reservation_plan",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("room_id"),
        sa.UniqueConstraint("plan_id", name="uq_room_action_reservations_plan"),
    )


def downgrade() -> None:
    op.drop_table("room_action_reservations")
    op.drop_index("ix_action_plan_runs_room_status", table_name="action_plan_runs")
    op.drop_table("action_plan_runs")
    op.drop_index(
        "ix_adjudication_commands_room_action",
        table_name="adjudication_command_executions",
    )
    op.drop_column("adjudication_command_executions", "action_request_id")
