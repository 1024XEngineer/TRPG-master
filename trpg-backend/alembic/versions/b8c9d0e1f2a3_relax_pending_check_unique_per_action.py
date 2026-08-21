"""放宽「一个动作至多一次检定」的唯一约束 (#398)

Revision ID: b8c9d0e1f2a3
Revises: b9c0d1e2f3a4

`uq_pending_check_decisions_room_action` 把「一个动作至多一个
PendingCheckDecision」写死在了 schema 里。这在被动检定接通之前一直成立：检定
只可能由玩家的动作发起，一次动作发起一次。

#398 §阶段三 之后不再成立——规则可以在一个动作提交的效果链**中间**要求一次
检定，而那个动作自己可能已经掷过一次骰了。《追书人》的地穴终局正是如此：玩家
先掷一次技能，提交的效果把 `cemetery_figure.true_form_seen` 翻成 true，
`first_sight_of_douglas` 随即要求一次理智检定。

真正需要保护的不变量是「同一个动作不能同时挂着两个**未结算**的检定」，而不是
「一辈子只能有一个」。所以改成条件唯一索引：只在 awaiting_skill_choice /
rolled 两个未结算状态上唯一，已经 resolved / cancelled 的旧记录不再参与。
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | Sequence[str] | None = "d1e2f3a4b5c6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_pending_check_decisions_room_action_open"
_CONSTRAINT = "uq_pending_check_decisions_room_action"
_OPEN = sa.text("status IN ('awaiting_skill_choice', 'rolled')")


def upgrade() -> None:
    with op.batch_alter_table("pending_check_decisions") as batch:
        batch.drop_constraint(_CONSTRAINT, type_="unique")
    op.create_index(
        _INDEX,
        "pending_check_decisions",
        ["room_id", "action_request_id"],
        unique=True,
        sqlite_where=_OPEN,
        postgresql_where=_OPEN,
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="pending_check_decisions")
    with op.batch_alter_table("pending_check_decisions") as batch:
        batch.create_unique_constraint(_CONSTRAINT, ["room_id", "action_request_id"])
