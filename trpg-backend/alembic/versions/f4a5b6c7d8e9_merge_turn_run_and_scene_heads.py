"""Merge TurnRun cutover and scene-transition migration branches."""

from collections.abc import Sequence

revision: str = "f4a5b6c7d8e9"
down_revision: str | Sequence[str] | None = ("b2c3d4e5f6a7", "e0f1a2b3c4d5")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
