"""add room host speech voice

Revision ID: f2a7c9d1e4b6
Revises: e4b6c8d0f2a1
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f2a7c9d1e4b6"
down_revision: str | Sequence[str] | None = "e4b6c8d0f2a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rooms",
        sa.Column("host_speech_voice_type", sa.String(length=200), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rooms", "host_speech_voice_type")
