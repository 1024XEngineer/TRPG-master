"""record the TurnRun cutover and bounded legacy recovery window

Revision ID: b2c3d4e5f6a7
Revises: c7d8e9f0a1b2
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | Sequence[str] | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "turn_run_cutover",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("cutover_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("legacy_recovery_until", sa.DateTime(timezone=True), nullable=False),
    )
    # Activation is deliberately separate from schema migration. During a
    # rolling deploy, old writers may still create Engine-only executions after
    # this table is installed; treating migration time as cutover would make
    # those actions unrecoverable. Deploy tooling inserts the singleton only
    # after all legacy writers have been drained.


def downgrade() -> None:
    op.drop_table("turn_run_cutover")
