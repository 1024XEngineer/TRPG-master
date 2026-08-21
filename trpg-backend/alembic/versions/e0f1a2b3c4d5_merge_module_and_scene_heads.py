"""Merge module-content and scene-transition migration branches."""

from collections.abc import Sequence

revision: str = "e0f1a2b3c4d5"
down_revision: str | Sequence[str] | None = ("d4f1a2b3c5e7", "d9e0f1a2b3c4")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
