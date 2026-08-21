"""增加长期记忆和玩家独立对话摘要投影。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "memory_entries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("subject_id", sa.String(length=100), nullable=False),
        sa.Column("object_id", sa.String(length=100), nullable=True),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("epistemic_status", sa.String(length=30), nullable=False),
        sa.Column("visibility", sa.String(length=30), nullable=False),
        sa.Column("participants", sa.JSON(), nullable=False),
        sa.Column("location_id", sa.String(length=100), nullable=True),
        sa.Column("source_event_id", sa.String(length=100), nullable=False),
        sa.Column("source_sequence", sa.BigInteger(), nullable=False),
        sa.Column("source_revision", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "room_id", "subject_id", "source_event_id", "kind", name="uq_memory_entries_source"
        ),
    )
    op.create_index(
        "ix_memory_entries_scope", "memory_entries", ["room_id", "subject_id", "visibility"]
    )
    op.create_index(
        "ix_memory_entries_entity", "memory_entries", ["room_id", "object_id", "location_id"]
    )
    op.create_table(
        "conversation_summaries",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("summary_json", sa.JSON(), nullable=False),
        sa.Column("through_event_sequence", sa.BigInteger(), nullable=False),
        sa.Column("pending_through_sequence", sa.BigInteger(), nullable=False),
        sa.Column("source_revision", sa.String(length=100), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"]),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "player_id", name="uq_conversation_summaries_scope"),
    )
    op.create_index(
        "ix_conversation_summaries_tasks", "conversation_summaries", ["status", "next_attempt_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_summaries_tasks", table_name="conversation_summaries")
    op.drop_table("conversation_summaries")
    op.drop_index("ix_memory_entries_entity", table_name="memory_entries")
    op.drop_index("ix_memory_entries_scope", table_name="memory_entries")
    op.drop_table("memory_entries")
