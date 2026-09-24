"""add_event_recurrence_weekly

Revision ID: wk1a2b3c4d5e
Revises: 293794bf9f09
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'wk1a2b3c4d5e'
down_revision: Union[str, None] = '293794bf9f09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'events',
        sa.Column('recurrence_day_of_week', sa.Integer(), nullable=True)
    )

    # `recurrence_day` (1-31) is only meaningful for MONTHLY/YEARLY; WEEKLY
    # uses `recurrence_day_of_week` (0=Monday..6=Sunday) instead, so the old
    # blanket "day is required" constraint has to be split by frequency.
    op.drop_constraint('ck_events_recurrence_required', 'events', type_='check')
    op.create_check_constraint(
        'ck_events_recurrence_required',
        'events',
        "is_recurring = false OR (recurrence_frequency IS NOT NULL AND "
        "(recurrence_day IS NOT NULL OR recurrence_day_of_week IS NOT NULL))"
    )
    op.create_check_constraint(
        'ck_events_monthly_yearly_day',
        'events',
        "recurrence_frequency NOT IN ('MONTHLY', 'YEARLY') OR recurrence_day IS NOT NULL"
    )
    op.create_check_constraint(
        'ck_events_weekly_day_of_week',
        'events',
        "recurrence_frequency != 'WEEKLY' OR recurrence_day_of_week IS NOT NULL"
    )
    op.create_check_constraint(
        'ck_events_weekly_gregorian_only',
        'events',
        "recurrence_frequency != 'WEEKLY' OR recurrence_date_system = 'GREGORIAN'"
    )


def downgrade() -> None:
    op.drop_constraint('ck_events_weekly_gregorian_only', 'events', type_='check')
    op.drop_constraint('ck_events_weekly_day_of_week', 'events', type_='check')
    op.drop_constraint('ck_events_monthly_yearly_day', 'events', type_='check')
    op.drop_constraint('ck_events_recurrence_required', 'events', type_='check')

    # Pre-weekly schema has no weekday column and no WEEKLY dispatcher.
    # The old expand_occurrences else-branch treats unknown frequencies as
    # monthly, so leaving frequency='WEEKLY' plus a placeholder recurrence_day
    # would render weekly events as "monthly on the 1st" in lists and feeds.
    # Convert those rows to one-off events (start_date/end_date already hold
    # the current occurrence) instead of inventing a monthly rule.
    op.execute(
        """
        UPDATE events
        SET is_recurring = false,
            recurrence_frequency = NULL,
            recurrence_date_system = NULL,
            recurrence_calendar_type = NULL,
            recurrence_month = NULL,
            recurrence_day = NULL
        WHERE is_recurring = true AND recurrence_frequency = 'WEEKLY'
        """
    )
    op.create_check_constraint(
        'ck_events_recurrence_required',
        'events',
        'is_recurring = false OR (recurrence_frequency IS NOT NULL AND recurrence_day IS NOT NULL)'
    )

    op.drop_column('events', 'recurrence_day_of_week')
