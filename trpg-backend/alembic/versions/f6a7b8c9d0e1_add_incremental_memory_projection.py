"""增加长期记忆增量投影游标和统一来源时间。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建房间投影高水位，并为旧记忆保守回填来源时间。"""
    op.add_column(
        "memory_entries",
        sa.Column(
            "source_created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # 历史记录无法再可靠区分两类来源时间，使用原投影时间保持稳定顺序。
    op.execute(sa.text("UPDATE memory_entries SET source_created_at = created_at"))
    op.create_index(
        "ix_memory_entries_room_source_created",
        "memory_entries",
        ["room_id", "source_created_at"],
    )
    op.create_table(
        "memory_projection_cursors",
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("event_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("event_id", sa.String(length=100), nullable=True),
        sa.Column("game_sequence", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["room_id"], ["game_sessions.room_id"]),
        sa.PrimaryKeyConstraint("room_id"),
    )


def downgrade() -> None:
    """移除增量游标，并恢复旧版记忆表结构。"""
    op.drop_table("memory_projection_cursors")
    op.drop_index("ix_memory_entries_room_source_created", table_name="memory_entries")
    op.drop_column("memory_entries", "source_created_at")
