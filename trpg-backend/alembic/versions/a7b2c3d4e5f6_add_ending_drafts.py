"""add grounded ending drafts and confirmation commands

Revision ID: a7b2c3d4e5f6
Revises: f6a1b2c3d4e5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b2c3d4e5f6"
down_revision: str | None = "f6a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ending_drafts",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.String(length=100), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column("player_id", sa.String(length=100), nullable=False),
        sa.Column("anchor_id", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("draft_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_ending_draft_version"),
        sa.CheckConstraint(
            "status IN ('active', 'confirmed', 'expired')",
            name="ck_ending_draft_status",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("room_id", "draft_id", name="pk_ending_drafts"),
        sa.UniqueConstraint("room_id", "request_id", name="uq_ending_drafts_request"),
    )
    op.create_table(
        "ending_command_executions",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("committed_state_version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "committed_state_version >= 0",
            name="ck_ending_command_state_version",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("room_id", "request_id", name="pk_ending_command_executions"),
    )


def downgrade() -> None:
    op.drop_table("ending_command_executions")
    op.drop_table("ending_drafts")
