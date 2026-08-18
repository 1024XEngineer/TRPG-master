"""add character template portraits

Revision ID: a3c4d5e6f7b8
Revises: e9a1b2c3d4f5
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3c4d5e6f7b8"
down_revision: str | Sequence[str] | None = "e9a1b2c3d4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "user_character_template_portraits",
        sa.Column("template_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False),
        sa.Column("content_type", sa.String(length=50), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "size_bytes > 0",
            name="ck_user_character_template_portraits_size_positive",
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["user_character_templates.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("template_id"),
    )


def downgrade() -> None:
    op.drop_table("user_character_template_portraits")
