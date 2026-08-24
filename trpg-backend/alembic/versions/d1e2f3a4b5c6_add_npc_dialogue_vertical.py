"""为结构化 NPC 对话增加冻结受众、任务恢复字段和 NPC 素材映射。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: str | Sequence[str] | None = "c0d1e2f3a4b5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """保守升级既有数据，新增字段均先提供可回填默认值。"""

    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_constraint("ck_events_visibility", type_="check")
        batch_op.create_check_constraint(
            "ck_events_visibility",
            "visibility IN ('public', 'player_scoped', 'scene_scoped')",
        )

    op.create_table(
        "event_audiences",
        sa.Column("event_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("event_id", "player_id", name="pk_event_audiences"),
    )
    op.create_index(
        "ix_event_audiences_player_event",
        "event_audiences",
        ["player_id", "event_id"],
    )

    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.drop_constraint("ck_host_action_queue_status", type_="check")
        batch_op.add_column(
            sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False)
        )
        batch_op.add_column(sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("lease_owner", sa.String(length=200), nullable=True))
        batch_op.add_column(
            sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch_op.add_column(
            sa.Column("result_event_ids", sa.JSON(), server_default="[]", nullable=False)
        )
    # 旧 started 只表示已从 FIFO 交给 Keeper，无法恢复，按既有语义视为完成。
    op.execute("UPDATE host_action_queue SET status = 'completed' WHERE status = 'started'")
    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.create_check_constraint(
            "ck_host_action_queue_status",
            "status IN ('queued', 'processing', 'retryable_failure', 'completed', "
            "'failed', 'cancelled', 'discarded')",
        )
        batch_op.create_check_constraint(
            "ck_host_action_queue_attempt_count",
            "attempt_count >= 0",
        )
        batch_op.create_check_constraint(
            "ck_host_action_queue_processing_lease",
            "(status = 'processing' AND lease_owner IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status != 'processing' AND lease_owner IS NULL "
            "AND lease_expires_at IS NULL)",
        )

    with op.batch_alter_table("module_assets") as batch_op:
        batch_op.add_column(sa.Column("entity_id", sa.String(length=200), nullable=True))
        batch_op.create_check_constraint(
            "ck_module_assets_entity_id_nonempty",
            "entity_id IS NULL OR length(trim(entity_id)) > 0",
        )
        batch_op.create_unique_constraint(
            "uq_module_assets_entity_type",
            ["scenario_id", "entity_id", "asset_type"],
        )


def downgrade() -> None:
    """移除 NPC 对话基础设施；降级不会删除原始 Event。"""

    with op.batch_alter_table("module_assets") as batch_op:
        batch_op.drop_constraint("uq_module_assets_entity_type", type_="unique")
        batch_op.drop_constraint("ck_module_assets_entity_id_nonempty", type_="check")
        batch_op.drop_column("entity_id")

    # 新终态降回旧模型前统一收敛，避免旧状态约束创建失败。
    op.execute(
        "UPDATE host_action_queue SET status = 'started', lease_owner = NULL, "
        "lease_expires_at = NULL, next_attempt_at = NULL "
        "WHERE status IN ('processing', 'retryable_failure', 'completed', 'failed')"
    )
    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.drop_constraint("ck_host_action_queue_processing_lease", type_="check")
        batch_op.drop_constraint("ck_host_action_queue_attempt_count", type_="check")
        batch_op.drop_constraint("ck_host_action_queue_status", type_="check")
        batch_op.drop_column("result_event_ids")
        batch_op.drop_column("lease_expires_at")
        batch_op.drop_column("lease_owner")
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("attempt_count")
        batch_op.create_check_constraint(
            "ck_host_action_queue_status",
            "status IN ('queued', 'started', 'cancelled', 'discarded')",
        )

    op.drop_index("ix_event_audiences_player_event", table_name="event_audiences")
    op.drop_table("event_audiences")
    # 旧版本不认识 scene_scoped；保守退回发起玩家私有，不能改成 public 泄露历史对话。
    op.execute("UPDATE events SET visibility = 'player_scoped' WHERE visibility = 'scene_scoped'")
    with op.batch_alter_table("events") as batch_op:
        batch_op.drop_constraint("ck_events_visibility", type_="check")
        batch_op.create_check_constraint(
            "ck_events_visibility",
            "visibility IN ('public', 'player_scoped')",
        )
