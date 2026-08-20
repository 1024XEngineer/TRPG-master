"""为多人共享场景切换增加持久化全员确认提案。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d9e0f1a2b3c4"
down_revision: str | Sequence[str] | None = "c7d8e9f0a1b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scene_transition_proposals",
        sa.Column("room_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("proposal_id", sa.String(length=100), nullable=False),
        sa.Column("source_revision", sa.BigInteger(), nullable=False),
        sa.Column("proposal_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("player_id", sa.String(length=100), nullable=False),
        sa.Column("action_request_id", sa.String(length=200), nullable=False),
        sa.Column("parent_action_id", sa.String(length=200), nullable=False),
        sa.Column("requester_player_id", sa.String(length=100), nullable=False),
        sa.Column("source_scene_id", sa.String(length=200), nullable=False),
        sa.Column("target_scene_id", sa.String(length=200), nullable=False),
        sa.Column("required_player_ids", sa.JSON(), nullable=False),
        sa.Column("accepted_player_ids", sa.JSON(), nullable=False),
        sa.Column("adjudication_json", sa.JSON(), nullable=False),
        sa.Column("execution_json", sa.JSON(), nullable=False),
        sa.Column("committed_revision", sa.BigInteger(), nullable=True),
        sa.Column("narration_persisted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "proposal_version >= 1",
            name="ck_scene_transition_proposal_version",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'stale')",
            name="ck_scene_transition_proposal_status",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["game_sessions.room_id"],
            name="fk_scene_transition_room",
        ),
        sa.PrimaryKeyConstraint(
            "room_id",
            "proposal_id",
            name="pk_scene_transition_proposals",
        ),
    )
    op.create_index(
        "ix_scene_transition_proposals_room_status",
        "scene_transition_proposals",
        ["room_id", "status", "updated_at"],
        unique=False,
    )
    with op.batch_alter_table("action_plan_runs") as batch_op:
        batch_op.drop_constraint("ck_action_plan_runs_status", type_="check")
        batch_op.create_check_constraint(
            "ck_action_plan_runs_status",
            "status IN ('active', 'checkpointed', 'waiting_for_player', "
            "'awaiting_time_consent', 'awaiting_scene_consent', "
            "'needs_clarification', 'retryable_failure', 'awaiting_narration', "
            "'completed', 'cancelled', 'stopped')",
        )


def downgrade() -> None:
    with op.batch_alter_table("action_plan_runs") as batch_op:
        batch_op.drop_constraint("ck_action_plan_runs_status", type_="check")
        batch_op.create_check_constraint(
            "ck_action_plan_runs_status",
            "status IN ('active', 'checkpointed', 'waiting_for_player', "
            "'awaiting_time_consent', 'needs_clarification', 'retryable_failure', "
            "'awaiting_narration', 'completed', 'cancelled', 'stopped')",
        )
    op.drop_index(
        "ix_scene_transition_proposals_room_status",
        table_name="scene_transition_proposals",
    )
    op.drop_table("scene_transition_proposals")
