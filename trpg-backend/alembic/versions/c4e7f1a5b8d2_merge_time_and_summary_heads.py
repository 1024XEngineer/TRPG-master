"""合并时间点回填与摘要复合游标迁移头。"""

from collections.abc import Sequence

revision: str = "c4e7f1a5b8d2"
down_revision: str | tuple[str, str] | None = (
    "b3d6f9a2c4e7",
    "g8b9c0d1e2f3",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """两个父迁移已经完成全部结构变更。"""


def downgrade() -> None:
    """降级仅把版本图重新分成两个父 head。"""
