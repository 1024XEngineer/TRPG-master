"""为玩家消息增加频道，并持久化主持行动的结构化接收者。"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: str | Sequence[str] | None = "b9c0d1e2f3a4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """保守回填旧数据后，用数据库约束固定频道和接收者组合。"""

    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.add_column(
            sa.Column("channel", sa.String(length=20), server_default="discussion", nullable=False)
        )
        batch_op.add_column(sa.Column("actor_id", sa.String(length=100), nullable=True))
        batch_op.create_check_constraint(
            "ck_chat_messages_channel",
            "channel IN ('discussion', 'roleplay')",
        )
        batch_op.create_check_constraint(
            "ck_chat_messages_channel_actor",
            "(channel = 'discussion' AND actor_id IS NULL) OR "
            "(channel = 'roleplay' AND actor_id IS NOT NULL)",
        )

    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.add_column(
            sa.Column(
                "recipient_kind",
                sa.String(length=20),
                server_default="keeper",
                nullable=False,
            )
        )
        batch_op.add_column(sa.Column("recipient_entity_id", sa.String(length=200), nullable=True))
        batch_op.add_column(
            sa.Column(
                "recipient_explicit",
                sa.Boolean(),
                server_default=sa.true(),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_host_action_queue_recipient_kind",
            "recipient_kind IN ('keeper', 'npc')",
        )
        batch_op.create_check_constraint(
            "ck_host_action_queue_recipient",
            "(recipient_kind = 'keeper' AND recipient_entity_id IS NULL) OR "
            "(recipient_kind = 'npc' AND recipient_entity_id IS NOT NULL "
            "AND length(trim(recipient_entity_id)) > 0 AND recipient_explicit)",
        )


def downgrade() -> None:
    """删除本 PR 新增的约束和字段，保留原有消息及队列数据。"""

    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.drop_constraint("ck_host_action_queue_recipient", type_="check")
        batch_op.drop_constraint("ck_host_action_queue_recipient_kind", type_="check")
        batch_op.drop_column("recipient_explicit")
        batch_op.drop_column("recipient_entity_id")
        batch_op.drop_column("recipient_kind")

    with op.batch_alter_table("chat_messages") as batch_op:
        batch_op.drop_constraint("ck_chat_messages_channel_actor", type_="check")
        batch_op.drop_constraint("ck_chat_messages_channel", type_="check")
        batch_op.drop_column("actor_id")
        batch_op.drop_column("channel")
