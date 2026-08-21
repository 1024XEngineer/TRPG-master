"""为 @主持人 串行主链增加持久化行动队列。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b9c0d1e2f3a4"
down_revision: str | Sequence[str] | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "host_action_queue",
        sa.Column("room_id", sa.Uuid(as_uuid=False), nullable=False),
        sa.Column("item_id", sa.String(length=100), nullable=False),
        sa.Column("client_action_id", sa.String(length=200), nullable=False),
        sa.Column("player_id", sa.String(length=100), nullable=False),
        sa.Column("actor_id", sa.String(length=100), nullable=False),
        sa.Column("utterance", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("position >= 1", name="ck_host_action_queue_position"),
        sa.CheckConstraint(
            "status IN ('queued', 'started', 'cancelled', 'discarded')",
            name="ck_host_action_queue_status",
        ),
        sa.ForeignKeyConstraint(
            ["room_id"],
            ["game_sessions.room_id"],
            name="fk_host_action_queue_room",
        ),
        sa.PrimaryKeyConstraint("room_id", "item_id", name="pk_host_action_queue"),
        sa.UniqueConstraint(
            "room_id",
            "client_action_id",
            name="uq_host_action_queue_client_action",
        ),
    )
    op.create_index(
        "ix_host_action_queue_room_status_position",
        "host_action_queue",
        ["room_id", "status", "position"],
        unique=False,
    )
    op.create_index(
        "uq_host_action_queue_pending_player",
        "host_action_queue",
        ["room_id", "player_id"],
        unique=True,
        sqlite_where=sa.text("status = 'queued'"),
        postgresql_where=sa.text("status = 'queued'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_host_action_queue_pending_player",
        table_name="host_action_queue",
    )
    op.drop_index(
        "ix_host_action_queue_room_status_position",
        table_name="host_action_queue",
    )
    op.drop_table("host_action_queue")
