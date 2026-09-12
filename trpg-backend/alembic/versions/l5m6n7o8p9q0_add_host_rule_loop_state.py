"""Persist composite host-action loop state."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "l5m6n7o8p9q0"
down_revision: str | Sequence[str] | None = "k4l5m6n7o8p9"
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


def downgrade() -> None:
    # Preserve committed results, but never replay a partial composite action
    # as a fresh legacy plan after application rollback.
    op.execute(
        sa.text(
            "UPDATE host_action_queue SET execution_route = 'delegate_to_legacy', "
            "status = CASE WHEN status IN ('completed', 'failed', 'cancelled', 'discarded') "
            "THEN status ELSE 'failed' END, lease_owner = NULL, lease_expires_at = NULL, "
            "next_attempt_at = NULL WHERE execution_route = 'composite_rule'"
        )
    )
    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.drop_constraint("ck_host_action_queue_execution_route", type_="check")
        batch_op.create_check_constraint(
            "ck_host_action_queue_execution_route",
            "execution_route IS NULL OR execution_route IN "
            "('unresolved', 'direct_response', 'rule_once', 'delegate_to_legacy', "
            "'needs_clarification')",
        )
        batch_op.drop_column("rule_loop_json")
