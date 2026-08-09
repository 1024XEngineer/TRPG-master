"""add inventory import drafts and idempotent commands

Revision ID: f6a1b2c3d4e5
Revises: e225a1b2c3d4
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a1b2c3d4e5"
down_revision: str | None = "e225a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "inventory_import_drafts",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("draft_id", sa.String(length=100), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column("player_id", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("draft_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_inventory_import_draft_version"),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("room_id", "draft_id", name="pk_inventory_import_drafts"),
        sa.UniqueConstraint("room_id", "request_id", name="uq_inventory_import_drafts_request"),
    )
    op.create_table(
        "inventory_command_executions",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("request_id", sa.String(length=200), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("committed_state_version", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "committed_state_version >= 0",
            name="ck_inventory_command_state_version",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("room_id", "request_id", name="pk_inventory_command_executions"),
    )


def downgrade() -> None:
    op.drop_table("inventory_command_executions")
    op.drop_table("inventory_import_drafts")
