"""reset character template library (#337)

Revision ID: d7e8f9a0b1c2
Revises: c1d2e3f4a5b6
Create Date: 2026-08-17

清空 `user_character_templates`，并把 `characters.based_on_template_id` 置空。

这些记录是 #121「完成建卡时自动保存」的产物。它们从来没有任何界面能列出、
选用或删除——`/me/character-templates` 四个端点在 #337 之前全是
`NOT_IMPLEMENTED` 桩，`basedOnTemplateId` 那条复用路径也是。而
`_mark_character_modified()` 每次存草稿都会清掉 `based_on_template_id`，
于是「完成 → 改一笔 → 再完成」会再存一条，只进不出。

#337 把方向倒过来（卡库卡是玩家显式保存的资产，房间角色卡是它的一份拷贝）后，
留着这批记录只会让玩家第一次打开卡库就看到一堆同名重复条目。项目仍在测试阶段，
直接清掉。

只删数据，不动表结构：`based_on_template_id` 的外键仍然是 `NO ACTION`，
删除卡库卡时对引用行的置空由 service 层显式执行。放在数据库层做不到可验证——
本地和全部测试跑的 SQLite `PRAGMA foreign_keys = 0`，外键约束根本不触发，
只有线上 PostgreSQL 才会执行它，等于写一个测试永远覆盖不到的保证。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: str | Sequence[str] | None = "c1d2e3f4a5b6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # 先断引用再删行：反过来的话，在真正强制外键的 PostgreSQL 上会直接失败。
    op.execute(sa.text("UPDATE characters SET based_on_template_id = NULL"))
    op.execute(sa.text("DELETE FROM user_character_templates"))


def downgrade() -> None:
    """Downgrade schema."""
    # 删掉的卡库记录无法复原，降级只是不再阻塞——这批数据本来就没有任何入口
    # 能访问到，恢复它们也没有意义。
