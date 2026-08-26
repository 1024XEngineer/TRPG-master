"""Persist A1 keeper entry routing decisions."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "h1i2j3k4l5m6"
# The repository currently has the user reconciliation head and the summary
# cursor head.  Depend on both so this migration does not create a third head.
down_revision: str | Sequence[str] | None = ("b1c2d3e4f5a6", "g8b9c0d1e2f3")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.add_column(
            sa.Column(
                "execution_route",
                sa.String(length=30),
                nullable=True,
                server_default="unresolved",
            )
        )
        batch_op.add_column(sa.Column("direct_response_text", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("execution_provenance", sa.String(length=40), nullable=True))
        batch_op.create_check_constraint(
            "ck_host_action_queue_execution_route",
            "execution_route IS NULL OR execution_route IN "
            "('unresolved', 'direct_response', 'delegate_to_legacy')",
        )
    # Keep pre-A rows NULL so the application can identify them as legacy
    # actions.  The server default applies only to rows inserted after this
    # migration; backfilling old rows to ``unresolved`` would route them through
    # A1 after a restart and violate the compatibility contract.
    op.execute(sa.text("UPDATE host_action_queue SET execution_route = NULL"))


def downgrade() -> None:
    with op.batch_alter_table("host_action_queue") as batch_op:
        batch_op.drop_constraint("ck_host_action_queue_execution_route", type_="check")
        batch_op.drop_column("execution_provenance")
        batch_op.drop_column("direct_response_text")
        batch_op.drop_column("execution_route")
