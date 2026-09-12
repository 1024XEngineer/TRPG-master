"""Track summary source consumption and rebuild incomplete legacy summaries."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "k4l5m6n7o8p9"
down_revision: str | None = "j3k4l5m6n7o8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "conversation_summaries",
        sa.Column("projection_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "conversation_summary_receipts",
        sa.Column("summary_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("consumed_chars", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("complete", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["summary_id"], ["conversation_summaries.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("summary_id", "event_id"),
    )


def downgrade() -> None:
    op.drop_table("conversation_summary_receipts")
    op.drop_column("conversation_summaries", "projection_version")
