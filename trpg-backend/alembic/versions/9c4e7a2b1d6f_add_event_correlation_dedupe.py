"""add event correlation dedupe

Revision ID: 9c4e7a2b1d6f
Revises: 8f3d2c1b0a9e
Create Date: 2026-07-23 14:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9c4e7a2b1d6f"
down_revision: str | Sequence[str] | None = "8f3d2c1b0a9e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """为旧 events 流水增加可空关联键和房间内持久化去重约束。"""
    op.add_column(
        "events",
        sa.Column("correlation_id", sa.String(length=200), nullable=True),
    )
    with op.batch_alter_table("events") as batch_op:
        batch_op.create_unique_constraint(
            "uq_events_room_type_correlation",
            ["room_id", "event_type", "correlation_id"],
        )


def downgrade() -> None:
    """移除 events 的关联键和去重约束。"""
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_constraint(
            "uq_events_room_type_correlation",
            type_="unique",
        )
        batch_op.drop_column("correlation_id")
