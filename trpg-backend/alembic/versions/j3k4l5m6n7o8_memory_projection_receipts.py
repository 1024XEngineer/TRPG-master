"""Track individual memory projection sources and upgrade legacy projections lazily."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j3k4l5m6n7o8"
down_revision: str | None = "i2j3k4l5m6n7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "memory_projection_cursors",
        sa.Column("projection_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "memory_projection_receipts",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("source_kind", sa.String(10), nullable=False),
        sa.Column("source_id", sa.String(100), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("room_id", "source_kind", "source_id"),
    )


def downgrade() -> None:
    op.drop_table("memory_projection_receipts")
    op.drop_column("memory_projection_cursors", "projection_version")
