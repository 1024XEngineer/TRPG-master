"""合并记忆系统与 main 分支模组约束迁移的 Alembic 分叉。"""

from collections.abc import Sequence

revision: str = "e5f6a7b8c9d0"
down_revision: tuple[str, str] = ("c3d4e5f6a7b8", "d4f1a2b3c5e7")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """无数据操作，仅汇合两条已经执行的迁移历史。"""


def downgrade() -> None:
    """无数据操作；降级时由 Alembic 分别回退两个父分支。"""
