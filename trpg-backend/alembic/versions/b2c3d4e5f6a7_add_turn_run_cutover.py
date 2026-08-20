"""record the TurnRun cutover and bounded legacy recovery window

Revision ID: b2c3d4e5f6a7
Revises: a3c4d5e6f7b8
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "a3c4d5e6f7b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "turn_run_cutover",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cutover_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("legacy_recovery_until", sa.DateTime(timezone=True), nullable=False),
    )
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        op.execute(
            sa.text(
                "INSERT INTO turn_run_cutover "
                "(id, cutover_at, legacy_recovery_until) "
                "VALUES (1, CURRENT_TIMESTAMP, datetime('now', '+30 days'))"
            )
        )
    else:
        op.execute(
            sa.text(
                "INSERT INTO turn_run_cutover "
                "(id, cutover_at, legacy_recovery_until) "
                "VALUES (1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP + INTERVAL '30 days')"
            )
        )


def downgrade() -> None:
    op.drop_table("turn_run_cutover")
