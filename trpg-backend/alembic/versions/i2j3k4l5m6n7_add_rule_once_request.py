"""Persist the validated Host Agent rule-once selection."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "i2j3k4l5m6n7"
down_revision: str | Sequence[str] | None = "h1i2j3k4l5m6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.drop_constraint("ck_host_action_queue_execution_route", type_="check")
        batch_op.create_check_constraint(
            "ck_host_action_queue_execution_route",
            "execution_route IS NULL OR execution_route IN "
            "('unresolved', 'direct_response', 'rule_once', 'delegate_to_legacy')",
        )
        batch_op.add_column(sa.Column("rule_request_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.drop_column("rule_request_json")
        batch_op.drop_constraint("ck_host_action_queue_execution_route", type_="check")
        batch_op.create_check_constraint(
            "ck_host_action_queue_execution_route",
            "execution_route IS NULL OR execution_route IN "
            "('unresolved', 'direct_response', 'delegate_to_legacy')",
        )
