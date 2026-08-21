"""修复已标记增量投影迁移但缺少统一来源时间列的数据库。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """按真实表结构补列和索引，兼容曾被提前标记到 head 的本地数据库。"""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("memory_entries")}
    if "source_created_at" not in columns:
        # SQLite 的 ALTER TABLE 只接受常量默认值；随后用原投影时间覆盖历史行。
        op.add_column(
            "memory_entries",
            sa.Column(
                "source_created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("'1970-01-01 00:00:00'"),
            ),
        )
        op.execute(sa.text("UPDATE memory_entries SET source_created_at = created_at"))

    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("memory_entries")}
    if "ix_memory_entries_room_source_created" not in indexes:
        op.create_index(
            "ix_memory_entries_room_source_created",
            "memory_entries",
            ["room_id", "source_created_at"],
        )


def downgrade() -> None:
    """不删除前序迁移拥有的列和索引，避免降级链重复删除。"""
