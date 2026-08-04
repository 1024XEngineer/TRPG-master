"""add explicit character occupation skill choices

Revision ID: e4b6c8d0f2a1
Revises: 3f8a1c2d4e5f
Create Date: 2026-08-04
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "e4b6c8d0f2a1"
down_revision: str | Sequence[str] | None = "3f8a1c2d4e5f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "characters",
        sa.Column("occupation_choice_skill_ids", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("characters", "occupation_choice_skill_ids")
