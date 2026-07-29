"""Add player-safe visibility and projection metadata to transport events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "3f8a1c2d4e5f"
down_revision: str | Sequence[str] | None = "2e4d6c7a8b90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("events", sa.Column("visibility", sa.String(length=20), nullable=True))
    op.add_column("events", sa.Column("actor_id", sa.String(length=200), nullable=True))
    op.add_column("events", sa.Column("scene_id", sa.String(length=200), nullable=True))
    op.add_column("events", sa.Column("view_revision", sa.String(length=200), nullable=True))

    op.execute(
        """
        UPDATE events
        SET visibility = CASE
            WHEN event_type = 'action.broadcast' THEN 'public'
            WHEN event_type = 'check.result' THEN 'player_scoped'
            WHEN event_type = 'narration.push' AND correlation_id IS NULL THEN 'public'
            WHEN event_type = 'narration.push' THEN 'player_scoped'
            WHEN player_id IS NOT NULL THEN 'player_scoped'
            ELSE 'public'
        END
        """
    )

    with op.batch_alter_table("events") as batch_op:
        batch_op.alter_column(
            "visibility",
            existing_type=sa.String(length=20),
            nullable=False,
        )
        batch_op.create_check_constraint(
            "ck_events_visibility",
            "visibility IN ('public', 'player_scoped')",
        )
        batch_op.create_check_constraint(
            "ck_events_player_scoped_owner",
            "visibility != 'player_scoped' OR player_id IS NOT NULL",
        )
        batch_op.create_index(
            "ix_events_room_created",
            ["room_id", "created_at"],
            unique=False,
        )
        batch_op.create_index(
            "ix_events_room_visibility_player_created",
            ["room_id", "visibility", "player_id", "created_at"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_index("ix_events_room_visibility_player_created")
        batch_op.drop_index("ix_events_room_created")
        batch_op.drop_constraint("ck_events_player_scoped_owner", type_="check")
        batch_op.drop_constraint("ck_events_visibility", type_="check")
        batch_op.drop_column("view_revision")
        batch_op.drop_column("scene_id")
        batch_op.drop_column("actor_id")
        batch_op.drop_column("visibility")
