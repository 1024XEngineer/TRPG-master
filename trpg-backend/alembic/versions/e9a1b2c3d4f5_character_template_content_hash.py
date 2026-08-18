"""character template content hash + uniqueness (#337)

Revision ID: e9a1b2c3d4f5
Revises: d7e8f9a0b1c2
Create Date: 2026-08-18

卡库里不该有两张一模一样的卡。判据是**内容**不是名字：两张真不同的卡可以同名，
字节相同的才算重复。

先去重再加约束——库里已经有重复行时直接加 UNIQUE 会失败（实测本地开发库 8 张
里有 3 张内容完全相同）。每组保留 `created_at` 最早的那张，并把引用被删行的
`characters.based_on_template_id` 改指到保留的那张上，免得留下悬空出处。

哈希算法必须和 `app/service/character.py:_template_content_hash` 完全一致：
sha256(json.dumps({"name":…, "data":…}, sort_keys=True, ensure_ascii=False,
separators=(",",":")))。这里重写一遍而不是 import，是因为迁移要能在未来任意
版本的代码上重放——import 了就会跟着业务代码一起漂移。
"""

import hashlib
import json
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e9a1b2c3d4f5"
down_revision: str | Sequence[str] | None = "d7e8f9a0b1c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _content_hash(name: str, raw_data: object) -> str:
    data = raw_data
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except json.JSONDecodeError:
            data = {}
    if not isinstance(data, dict):
        data = {}
    payload = json.dumps(
        {"name": name, "data": data},
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upgrade() -> None:
    """Upgrade schema."""
    connection = op.get_bind()

    with op.batch_alter_table("user_character_templates") as batch_op:
        batch_op.add_column(sa.Column("content_hash", sa.String(64), nullable=True))

    rows = connection.execute(
        sa.text(
            "SELECT id, user_id, system_id, name, data, created_at "
            "FROM user_character_templates ORDER BY created_at, id"
        )
    ).fetchall()

    kept: dict[tuple[str, str, str], str] = {}
    for row in rows:
        digest = _content_hash(row.name, row.data)
        key = (row.user_id, row.system_id, digest)
        survivor = kept.get(key)
        if survivor is None:
            # 每组第一条（created_at 最早）留下。
            kept[key] = row.id
            connection.execute(
                sa.text("UPDATE user_character_templates SET content_hash = :h WHERE id = :i"),
                {"h": digest, "i": row.id},
            )
            continue
        # 重复行：先把出处指到保留的那张，再删。反过来会留下悬空的
        # based_on_template_id（PostgreSQL 上甚至删不掉）。
        connection.execute(
            sa.text(
                "UPDATE characters SET based_on_template_id = :keep "
                "WHERE based_on_template_id = :drop"
            ),
            {"keep": survivor, "drop": row.id},
        )
        connection.execute(
            sa.text("DELETE FROM user_character_templates WHERE id = :i"),
            {"i": row.id},
        )

    with op.batch_alter_table("user_character_templates") as batch_op:
        batch_op.alter_column("content_hash", existing_type=sa.String(64), nullable=False)
        batch_op.create_unique_constraint(
            "uq_user_character_templates_content",
            ["user_id", "system_id", "content_hash"],
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("user_character_templates") as batch_op:
        batch_op.drop_constraint("uq_user_character_templates_content", type_="unique")
        batch_op.drop_column("content_hash")
