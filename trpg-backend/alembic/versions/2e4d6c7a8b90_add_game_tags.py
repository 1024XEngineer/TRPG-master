"""Add player-visible world/theme tags to games."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "2e4d6c7a8b90"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "games",
        sa.Column("tags", sa.JSON(), server_default="[]", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("games", "tags")
