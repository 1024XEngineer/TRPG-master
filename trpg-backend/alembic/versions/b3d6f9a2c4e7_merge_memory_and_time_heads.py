"""合并记忆投影与时间点回填的迁移头。"""

from collections.abc import Sequence

revision: str = "b3d6f9a2c4e7"
down_revision: str | Sequence[str] | None = (
    "f7a8b9c0d1e2",
    "a2c5e8b1d3f4",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """空操作：两条已经完成的迁移历史在此汇合。"""


def downgrade() -> None:
    """空操作：降级时由 Alembic 自动回退到两个父分支。"""
