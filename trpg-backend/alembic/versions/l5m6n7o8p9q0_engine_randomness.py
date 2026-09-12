"""Durable command randomness for resource effects and check recovery."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "l5m6n7o8p9q0"
down_revision: str | None = "k4l5m6n7o8p9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "engine_randomness",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("operation_key", sa.String(300), nullable=False),
        sa.Column("snapshot_json", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("room_id", "operation_key"),
    )


def downgrade() -> None:
    op.drop_table("engine_randomness")
