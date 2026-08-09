"""add independent RuleAgenda coordination version

Revision ID: b8c3d4e5f6a7
Revises: a7b2c3d4e5f6
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "b8c3d4e5f6a7"
down_revision: str | None = "a7b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("game_sessions") as batch_op:
        batch_op.add_column(
            sa.Column(
                "agenda_state_version",
                sa.BigInteger(),
                server_default="0",
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_game_sessions_agenda_state_version",
            "agenda_state_version >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("game_sessions") as batch_op:
        batch_op.drop_constraint(
            "ck_game_sessions_agenda_state_version",
            type_="check",
        )
        batch_op.drop_column("agenda_state_version")
