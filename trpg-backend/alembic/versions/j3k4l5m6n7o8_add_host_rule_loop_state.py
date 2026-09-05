"""Persist composite host-action loop state."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "j3k4l5m6n7o8"
down_revision: str | Sequence[str] | None = "i2j3k4l5m6n7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.add_column(sa.Column("rule_loop_json", sa.JSON(), nullable=True))
        batch_op.drop_constraint("ck_host_action_queue_execution_route", type_="check")
        batch_op.create_check_constraint(
            "ck_host_action_queue_execution_route",
            "execution_route IS NULL OR execution_route IN "
            "('unresolved', 'direct_response', 'rule_once', 'composite_rule', "
            "'delegate_to_legacy', 'needs_clarification')",
        )
    # Existing A/B/D queue records have no composite cursor. Store an explicit
    # empty JSON object so startup validation can distinguish migrated rows from
    # malformed non-JSON values while preserving legacy route behavior.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            sa.text(
                "UPDATE host_action_queue SET rule_loop_json = '{}'::json "
                "WHERE rule_loop_json IS NULL"
            )
        )
    else:
        op.execute(
            sa.text(
                "UPDATE host_action_queue SET rule_loop_json = '{}' WHERE rule_loop_json IS NULL"
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.drop_constraint("ck_host_action_queue_execution_route", type_="check")
        batch_op.create_check_constraint(
            "ck_host_action_queue_execution_route",
            "execution_route IS NULL OR execution_route IN "
            "('unresolved', 'direct_response', 'delegate_to_legacy', 'needs_clarification')",
        )
        batch_op.drop_column("rule_loop_json")
