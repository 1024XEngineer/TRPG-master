"""为长期记忆增加冻结玩家受众。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e7f8a9b0c1d2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """给记忆补受众字段，并把历史行保守回填为空数组。"""

    op.add_column(
        "memory_entries",
        sa.Column("audience_player_ids", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.execute(sa.text("UPDATE memory_entries SET audience_player_ids = '[]'"))
    with op.batch_alter_table("memory_entries") as batch_op:
        batch_op.alter_column("audience_player_ids", server_default=None)


def downgrade() -> None:
    """移除冻结受众字段。"""

    op.drop_column("memory_entries", "audience_player_ids")
