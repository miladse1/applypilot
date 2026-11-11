"""AI usage tracking, result cache, and per-user AI settings

Revision ID: c4e8a2f17d55
Revises: 7b2d1c4e9a10
Create Date: 2026-10-12 10:00:00
"""
from typing import Sequence, Union

from alembic import op

revision: str = "c4e8a2f17d55"
down_revision: Union[str, Sequence[str], None] = "7b2d1c4e9a10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The same additive step runs at API start-up, so this revision is idempotent.
    from app.core.schema import upgrade_connection

    upgrade_connection(op.get_bind())


def downgrade() -> None:
    # Additive only. Dropping tables would discard usage history.
    pass
