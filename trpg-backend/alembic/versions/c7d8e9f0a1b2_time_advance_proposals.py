"""新增多人共享时间推进提案表，为全员确认、幂等提交和断线恢复提供持久化依据。"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c7d8e9f0a1b2"
down_revision: str | Sequence[str] | None = "e9a1b2c3d4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建独立提案表；现有房间、GameState 和 ModuleVersion 均无需改写。"""

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
        sa.Column(
            "narration_persisted",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "proposal_version >= 1", name="ck_time_advance_proposal_version"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'rejected', 'expired', 'stale')",
            name="ck_time_advance_proposal_status",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"], ["game_sessions.room_id"], name="fk_time_advance_room"
        ),
        sa.PrimaryKeyConstraint(
            "room_id", "proposal_id", name="pk_time_advance_proposals"
        ),
        sa.UniqueConstraint(
            "room_id",
            "source_revision",
            name="uq_time_advance_room_revision",
        ),
    )
    op.create_index(
        "ix_time_advance_proposals_room_status",
        "time_advance_proposals",
        ["room_id", "status", "updated_at"],
        unique=False,
    )
    # ActionPlan 要在进程重启后准确区分“等检定”与“等时间确认”。
    # batch 模式同时兼容 SQLite 的表重建限制和 PostgreSQL。
    with op.batch_alter_table("action_plan_runs") as batch_op:
        batch_op.drop_constraint("ck_action_plan_runs_status", type_="check")
        batch_op.create_check_constraint(
            "ck_action_plan_runs_status",
            "status IN ('active', 'checkpointed', 'waiting_for_player', "
            "'awaiting_time_consent', 'needs_clarification', 'retryable_failure', "
            "'awaiting_narration', 'completed', 'cancelled', 'stopped')",
        )


def downgrade() -> None:
    """移除多人时间提案表。"""

    with op.batch_alter_table("action_plan_runs") as batch_op:
        batch_op.drop_constraint("ck_action_plan_runs_status", type_="check")
        batch_op.create_check_constraint(
            "ck_action_plan_runs_status",
            "status IN ('active', 'checkpointed', 'waiting_for_player', "
            "'needs_clarification', 'retryable_failure', 'awaiting_narration', "
            "'completed', 'cancelled', 'stopped')",
        )
    op.drop_index(
        "ix_time_advance_proposals_room_status",
        table_name="time_advance_proposals",
    )
    op.drop_table("time_advance_proposals")
