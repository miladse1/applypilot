"""job relevance, search profiles, assistant, resume layout

Revision ID: 7b2d1c4e9a10
Revises: 3131f0e7c999
Create Date: 2026-10-09 21:30:00
"""
from typing import Sequence, Union

from alembic import op

revision: str = "7b2d1c4e9a10"
down_revision: Union[str, Sequence[str], None] = "3131f0e7c999"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # The same additive step runs at API start-up, so this revision is idempotent.
    from app.core.schema import upgrade_connection

    upgrade_connection(op.get_bind())


def downgrade() -> None:
    # Additive only. Dropping columns would discard user data.
    pass
