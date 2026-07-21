"""unique player per room per account

Revision ID: 1a02058345ee
Revises: d6ed190ffc39
Create Date: 2026-07-21 18:39:46.259998

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1a02058345ee"
down_revision: str | Sequence[str] | None = "d6ed190ffc39"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """给 players 加 (room_id, user_id) 唯一约束。

    必须用 batch 模式：SQLite 不支持 `ALTER TABLE ... ADD CONSTRAINT`（autogenerate
    默认生成的 `op.create_unique_constraint` 在 SQLite 上直接 NotImplementedError），
    batch 模式会退化成"建新表→拷数据→改名"这套。PostgreSQL 上 batch 模式等价于
    普通 ALTER，不受影响。

    ⚠️ 如果本地已有库里存在「同一账号在同一房间有多行」的脏数据（#106 之前
    join_room 没有幂等，重复加入会建重复行），这条迁移会失败。开发库直接删掉
    `app.db` 重新 `alembic upgrade head` 即可。
    """
    with op.batch_alter_table("players") as batch_op:
        batch_op.create_unique_constraint("uq_players_room_user", ["room_id", "user_id"])


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("players") as batch_op:
        batch_op.drop_constraint("uq_players_room_user", type_="unique")
