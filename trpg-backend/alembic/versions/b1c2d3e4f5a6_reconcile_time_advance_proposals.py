"""Repair databases that recorded the time-proposal migration without its table."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "time_advance_proposals" in inspector.get_table_names():
        return

    op.create_table(
        "time_advance_proposals",
        sa.Column("room_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("proposal_id", sa.String(length=100), nullable=False),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("player_id", sa.String(length=100), nullable=False),
        sa.Column("action_request_id", sa.String(length=200), nullable=False),
        sa.Column("parent_action_id", sa.String(length=200), nullable=False),
        sa.Column("requester_player_id", sa.String(length=100), nullable=False),
        sa.Column("target_point_id", sa.String(length=100), nullable=False),
        sa.Column("target_day_index", sa.Integer(), nullable=False),
        sa.Column("target_hour_of_day", sa.Integer(), nullable=False),
        sa.Column("required_player_ids", sa.JSON(), nullable=False),
        sa.Column("accepted_player_ids", sa.JSON(), nullable=False),
        sa.Column("adjudication_json", sa.JSON(), nullable=False),
        sa.Column("execution_json", sa.JSON(), nullable=False),
        sa.Column("committed_revision", sa.BigInteger(), nullable=True),
        sa.Column("narration_persisted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("proposal_version >= 1", name="ck_time_advance_proposal_version"),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'stale')",
            name="ck_time_advance_proposal_status",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["game_sessions.room_id"], name="fk_time_advance_room"
        ),
        sa.PrimaryKeyConstraint("room_id", "proposal_id", name="pk_time_advance_proposals"),
    )
    op.create_index(
        "ix_time_advance_proposals_room_status",
        "time_advance_proposals",
        ["room_id", "status", "updated_at"],
    )


def downgrade() -> None:
    """Keep repaired data; the canonical c7 migration owns table removal."""

    # This migration repairs schema drift and cannot know whether it created the
    # table or merely observed the canonical c7 branch's table. Removing it here
    # can destroy valid proposal data and makes a merged-head downgrade attempt
    # to drop the same table twice. The earlier canonical migration remains the
    # sole owner of the destructive downgrade.
    pass
