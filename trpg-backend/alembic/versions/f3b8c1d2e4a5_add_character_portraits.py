"""新增角色当前头像表，将 AIGC 图片二进制持久化到数据库。

Revision ID: f3b8c1d2e4a5
Revises: e225a1b2c3d4
Create Date: 2026-08-10
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f3b8c1d2e4a5"
down_revision: str | Sequence[str] | None = "e225a1b2c3d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建每个角色最多一条记录的头像表。"""
    op.create_table(
        "character_portraits",
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_character_portraits_size_positive",
        ),
        sa.ForeignKeyConstraint(
            ["character_id"],
            ["characters.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("character_id"),
    )


def downgrade() -> None:
    """移除角色头像表；降级会删除已经持久化的头像数据。"""
    op.drop_table("character_portraits")
