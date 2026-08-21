"""修复部分旧数据库已标记迁移但缺少 listener_ids 列的结构漂移。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 线上/本地可能已经被错误标记到 b2；检查后再补列，保证重复升级安全。
    bind = op.get_bind()
    columns = {
        row[1] for row in bind.execute(sa.text("PRAGMA table_info(memory_entries)"))
    }
    if "listener_ids" not in columns:
        op.add_column(
            "memory_entries",
            sa.Column("listener_ids", sa.JSON(), nullable=False, server_default="[]"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    columns = {
        row[1] for row in bind.execute(sa.text("PRAGMA table_info(memory_entries)"))
    }
    if "listener_ids" in columns:
        op.drop_column("memory_entries", "listener_ids")
