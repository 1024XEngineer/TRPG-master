"""tighten module content schema version to v3 only (#384)

Revision ID: d4f1a2b3c5e7
Revises: c7d8e9f0a1b2
Create Date: 2026-08-20

ModuleContent v1/v2 的契约、发布链路与引擎双臂都已删除，库里只可能存在 v3 内容。
把 `ck_module_versions_content_schema_version` 从 `>= 1` 收紧到 `= 3`，让「非 v3
的行」在写入时就被数据库拒绝，而不是等到 `load_runtime` 解析失败。

列默认值必须同一次改掉。约束收紧之后 `server_default="1"` 就是一个必然违反约束的
默认值：任何不显式给出 `content_schema_version` 的插入都会直接撞约束失败。default
与 server_default 一起移到 3。

SQLite 不支持直接改 CHECK 约束，按仓库既有迁移的做法用 `batch_alter_table` 重建表。
重建时必须显式传入 `table_args`/`existing_server_default`，否则 batch 模式会按反射
到的旧定义重放，把刚改的东西还原回去。

升级前若库里真有非 3 的行（本仓库所有环境都没有），重建会因为新约束失败——这是有意
的，不静默删数据。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4f1a2b3c5e7"
down_revision: str | Sequence[str] | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT = "ck_module_versions_content_schema_version"


def upgrade() -> None:
    with op.batch_alter_table("module_versions") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT, type_="check")
        batch_op.alter_column(
            "content_schema_version",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default="3",
        )
        batch_op.create_check_constraint(_CONSTRAINT, "content_schema_version = 3")


def downgrade() -> None:
    with op.batch_alter_table("module_versions") as batch_op:
        batch_op.drop_constraint(_CONSTRAINT, type_="check")
        batch_op.alter_column(
            "content_schema_version",
            existing_type=sa.Integer(),
            existing_nullable=False,
            server_default="1",
        )
        batch_op.create_check_constraint(_CONSTRAINT, "content_schema_version >= 1")
