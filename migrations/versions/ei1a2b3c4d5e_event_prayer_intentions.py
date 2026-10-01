"""link events to allowed prayer intention subsets

Revision ID: ei1a2b3c4d5e
Revises: mu1a2b3c4d5e
Create Date: 2026-09-30 14:00:00.000000

When an event has no rows here, prayer requests may use any catalog intention.
When it has one or more rows, only those intentions are allowed for that event.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from migrations.idempotency import table_exists

revision: str = "ei1a2b3c4d5e"
down_revision: Union[str, None] = "mu1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    if table_exists("event_prayer_intentions"):
        return
    op.create_table(
        "event_prayer_intentions",
        sa.Column(
            "event_id",
            sa.UUID(),
            sa.ForeignKey("events.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "intention_id",
            sa.UUID(),
            sa.ForeignKey("prayer_intentions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("event_id", "intention_id"),
    )
    op.create_index(
        "idx_event_prayer_intentions_intention_id",
        "event_prayer_intentions",
        ["intention_id"],
    )


def downgrade() -> None:
    if not table_exists("event_prayer_intentions"):
        return
    op.drop_index(
        "idx_event_prayer_intentions_intention_id",
        table_name="event_prayer_intentions",
    )
    op.drop_table("event_prayer_intentions")
