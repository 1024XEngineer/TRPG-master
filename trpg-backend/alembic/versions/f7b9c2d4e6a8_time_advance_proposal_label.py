"""时间推进提案冗余保存玩家可见措辞 (#415)

Revision ID: f7b9c2d4e6a8
Revises: e2f3a4b5c6d7

多人时间确认的广播载荷从「第 1 天 22:00」收窄成模组声明的 label 之后，
`_pending_payload` / `_resolved_payload` 需要一个 label 才能构造。

解析 label 要 `TimePointSpec`，也就是要读 `ModuleVersion.content_json` 并把
整份 `ModuleContentV3` 校验一遍。广播路径为了一个字符串做这件事不划算，而且
每次重连覆盖都要再做一次，所以在建提案时就把解析结果冗余存下来。

精确的 `target_point_id` / `target_day_index` / `target_hour_of_day` **保留**：
它们不再进广播载荷，但仍然是提交时的校验依据和断线恢复的依据。收窄的是投影，
不是权威数据。

列可空是为了迁移前就已经挂在库里的提案：读取时按 `target_hour_of_day` 回退到
canonical segment 的缺省措辞。提案 TTL 只有 5 分钟，实际能撞上的窗口极小，但
回退比让广播炸掉便宜。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision: str = "f7b9c2d4e6a8"
down_revision: str | None = "e2f3a4b5c6d7"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "time_advance_proposals",
        sa.Column("target_label", sa.String(length=20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("time_advance_proposals", "target_label")
