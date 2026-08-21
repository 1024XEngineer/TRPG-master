"""为长期记忆增加可审计的 NPC 听众字段。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 旧投影没有听众信息，空数组表示未知，不把历史玩家原话升级成 NPC 亲历。
    op.add_column(
        "memory_entries",
        sa.Column("listener_ids", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade() -> None:
    # 某些旧数据库可能已标记过升级但实际缺列，回滚也必须保持幂等。
    bind = op.get_bind()
    columns = {row[1] for row in bind.execute(sa.text("PRAGMA table_info(memory_entries)"))}
    if "listener_ids" in columns:
        op.drop_column("memory_entries", "listener_ids")
