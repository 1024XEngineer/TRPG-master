"""为长局摘要增加基于 Event 时间和 ID 的复合游标。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "g8b9c0d1e2f3"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """添加摘要游标，并尽可能从旧 sequence 定位历史 Event。"""
    op.add_column(
        "conversation_summaries",
        sa.Column("through_event_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversation_summaries",
        sa.Column("through_event_id", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "conversation_summaries",
        sa.Column("pending_event_created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversation_summaries",
        sa.Column("pending_event_id", sa.String(length=100), nullable=True),
    )
    op.create_index(
        "ix_conversation_summaries_event_cursor",
        "conversation_summaries",
        ["room_id", "player_id", "through_event_created_at", "through_event_id"],
    )

    # 旧摘要的 sequence 是可见事件列表中的位置；逐条回填能同时兼容 SQLite 和 PostgreSQL。
    bind = op.get_bind()
    summaries = sa.table(
        "conversation_summaries",
        sa.column("id", sa.String()),
        sa.column("room_id", sa.String()),
        sa.column("player_id", sa.String()),
        sa.column("through_event_sequence", sa.Integer()),
        sa.column("through_event_created_at", sa.DateTime(timezone=True)),
        sa.column("through_event_id", sa.String()),
    )
    events = sa.table(
        "events",
        sa.column("id", sa.String()),
        sa.column("room_id", sa.String()),
        sa.column("player_id", sa.String()),
        sa.column("event_type", sa.String()),
        sa.column("visibility", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    rows = bind.execute(sa.select(summaries)).mappings().all()
    event_types = (
        "action.broadcast",
        "narration.push",
        "check.result",
        "dialogue.player",
        "dialogue.npc",
    )
    for row in rows:
        sequence = int(row["through_event_sequence"] or 0)
        if sequence <= 0:
            continue
        cursor = bind.execute(
            sa.select(events.c.created_at, events.c.id)
            .where(
                events.c.room_id == row["room_id"],
                events.c.event_type.in_(event_types),
                sa.or_(
                    events.c.visibility == "public",
                    events.c.player_id == row["player_id"],
                ),
            )
            .order_by(events.c.created_at, events.c.id)
            .offset(sequence - 1)
            .limit(1)
        ).first()
        if cursor is None:
            continue
        bind.execute(
            summaries.update()
            .where(summaries.c.id == row["id"])
            .values(
                through_event_created_at=cursor.created_at,
                through_event_id=cursor.id,
            )
        )


def downgrade() -> None:
    """移除复合游标，不删除既有摘要内容。"""
    op.drop_index("ix_conversation_summaries_event_cursor", table_name="conversation_summaries")
    op.drop_column("conversation_summaries", "pending_event_id")
    op.drop_column("conversation_summaries", "pending_event_created_at")
    op.drop_column("conversation_summaries", "through_event_id")
    op.drop_column("conversation_summaries", "through_event_created_at")
