"""Merge the chat and engine persistence migration branches."""

from collections.abc import Sequence

revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = ("c288fe8f2cdd", "b7e4c2d1a6f9")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
