"""合并记忆投影分叉头，恢复单一 head 以便常规升级。"""

from collections.abc import Sequence

revision: str = "f7a8b9c0d1e2"
down_revision: str | Sequence[str] | None = ("e2f3a4b5c6d7", "e7f8a9b0c1d2")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """空操作：这里只是把两条已经存在的迁移历史合到同一个 head。"""


def downgrade() -> None:
    """空操作：降级时由 Alembic 自动回退到两个父分支。"""
