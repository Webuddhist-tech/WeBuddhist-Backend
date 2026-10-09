"""add participation_type to group_event_participants

Revision ID: pt1a2b3c4d5e
Revises: ta7f8e9d0c1b2
Create Date: 2026-09-16 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "pt1a2b3c4d5e"
down_revision: Union[str, None] = "ta7f8e9d0c1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable on purpose: existing participants joined before the choice
    # existed, and a hybrid event has no correct value to backfill them with.
    op.add_column(
        "group_event_participants",
        sa.Column("participation_type", sa.String(length=10), nullable=True),
    )
    # Events that are online-only or offline-only leave no room for a choice,
    # so their existing participants can be filled in unambiguously.
    op.execute(
        """
        UPDATE group_event_participants AS p
        SET participation_type = e.event_format
        FROM events AS e
        WHERE e.id = p.event_id
          AND e.event_format IN ('online', 'offline')
          AND p.participation_type IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("group_event_participants", "participation_type")
