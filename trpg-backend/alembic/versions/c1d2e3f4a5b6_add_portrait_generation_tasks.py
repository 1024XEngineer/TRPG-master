"""新增可持久跟踪的角色生图后台任务表。

Revision ID: c1d2e3f4a5b6
Revises: b8c3d4e5f6a7
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | Sequence[str] | None = "b8c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """创建任务历史表及每个角色唯一活动任务索引。"""
    op.create_table(
        "portrait_generation_tasks",
        sa.Column("generation_id", sa.Uuid(), nullable=False),
        sa.Column("room_id", sa.Uuid(), nullable=False),
        sa.Column("character_id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False),
        sa.Column("failure_code", sa.String(40), nullable=True),
        sa.Column("style", sa.String(20), nullable=False),
        sa.Column("size", sa.String(20), nullable=False),
        sa.Column("prompt_summary", sa.String(1000), nullable=True),
        sa.Column("prompt_source", sa.String(40), nullable=True),
        sa.Column("portrait_version", sa.String(64), nullable=True),
        sa.Column("provider_task_id", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('queued', 'generating', 'cancelling', 'completed', 'failed', 'cancelled')",
            name="ck_portrait_generation_tasks_status",
        ),
        sa.ForeignKeyConstraint(["room_id"], ["rooms.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["character_id"], ["characters.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("generation_id"),
    )
    op.create_index(
        "uq_portrait_generation_tasks_active_character",
        "portrait_generation_tasks",
        ["character_id"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'generating', 'cancelling')"),
        postgresql_where=sa.text("status IN ('queued', 'generating', 'cancelling')"),
    )


def downgrade() -> None:
    """删除角色生图任务历史。"""
    op.drop_index(
        "uq_portrait_generation_tasks_active_character",
        table_name="portrait_generation_tasks",
    )
    op.drop_table("portrait_generation_tasks")
