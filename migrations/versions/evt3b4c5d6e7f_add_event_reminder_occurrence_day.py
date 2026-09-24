"""add occurrence day columns and per-day unique index to event_reminders

Revision ID: evt3b4c5d6e7f
Revises: mr1a2b3c4d5e
Create Date: 2026-09-23 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from migrations.idempotency import (
    column_exists,
    index_exists,
    table_exists,
    unique_constraint_exists,
)

# revision identifiers, used by Alembic.
revision: str = "evt3b4c5d6e7f"
down_revision: Union[str, None] = "mr1a2b3c4d5e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every row that predates this migration is a day-1 reminder, so the
# occurrence date comes from the event's own start_date rather than from
# fire_at: a T_MINUS_10 whose lead time crosses midnight fires on the
# previous calendar day, and keying off fire_at would file it under the
# wrong occurrence.
#
# `timezone` is unvalidated free text, so an unknown value would make
# `AT TIME ZONE` raise and abort the whole migration; anything Postgres
# does not recognize falls back to UTC, matching the runtime fallback in
# event_reminder_service.
_BACKFILL_OCCURRENCE_DATE = """
    UPDATE event_reminders r
       SET occurrence_date = (
           e.start_date AT TIME ZONE
           CASE
               WHEN e.timezone IN (SELECT name FROM pg_timezone_names)
               THEN e.timezone
               ELSE 'UTC'
           END
       )::date
      FROM events e
     WHERE e.id = r.event_id
       AND r.occurrence_date IS NULL
"""


def upgrade() -> None:
    if not table_exists("event_reminders"):
        return

    if not column_exists("event_reminders", "occurrence_date"):
        op.add_column(
            "event_reminders",
            sa.Column("occurrence_date", sa.Date(), nullable=True),
        )
        op.execute(_BACKFILL_OCCURRENCE_DATE)
        op.alter_column("event_reminders", "occurrence_date", nullable=False)

    # Null on a single-day occurrence, which keeps the reminder copy
    # unchanged; set only where a reminder is one day of a longer run.
    if not column_exists("event_reminders", "day_index"):
        op.add_column(
            "event_reminders",
            sa.Column("day_index", sa.SmallInteger(), nullable=True),
        )
    if not column_exists("event_reminders", "day_total"):
        op.add_column(
            "event_reminders",
            sa.Column("day_total", sa.SmallInteger(), nullable=True),
        )

    # Created before the old constraint goes, so the table is never without
    # uniqueness protection on a reminder's identity.
    if not index_exists("event_reminders", "uq_event_reminders_event_type_day"):
        op.create_index(
            "uq_event_reminders_event_type_day",
            "event_reminders",
            ["event_id", "reminder_type", "occurrence_date"],
            unique=True,
        )

    # uq_event_reminders_event_type - one row per (event, type) - is what the
    # per-day key replaces, and it has to go in the same migration that adds
    # the key. It cannot be deferred to a later release to protect a rolling
    # deploy: adding occurrence_date NOT NULL above already makes the previous
    # release's INSERT (which does not supply the column) fail, so keeping the
    # old constraint buys no extra compatibility while leaving a table that
    # physically cannot hold day 2 of a multi-day event. Dropping it here is
    # what makes EVENT_REMINDER_DAILY_ENABLED and
    # EVENT_REMINDER_RECURRING_ENABLED safe to turn on at all: both write
    # several rows per (event, type), one per occurrence date.
    if unique_constraint_exists("event_reminders", "uq_event_reminders_event_type"):
        op.drop_constraint(
            "uq_event_reminders_event_type",
            "event_reminders",
            type_="unique",
        )

    # idx_event_reminders_due is partial (undispatched, uncanceled) so it
    # cannot serve the retention purge, which sweeps by fire_at alone.
    if not index_exists("event_reminders", "idx_event_reminders_fire_at"):
        op.create_index(
            "idx_event_reminders_fire_at",
            "event_reminders",
            ["fire_at"],
            unique=False,
        )


def downgrade() -> None:
    # Restored before the per-day rows are lost with occurrence_date. This
    # fails if the daily or recurring flag ever ran: the extra days are real
    # rows that (event_id, reminder_type) cannot hold, and there is no
    # correct way to pick which day survives, so the duplicates have to be
    # cleared deliberately before downgrading.
    if table_exists("event_reminders") and not unique_constraint_exists(
        "event_reminders", "uq_event_reminders_event_type"
    ):
        op.create_unique_constraint(
            "uq_event_reminders_event_type",
            "event_reminders",
            ["event_id", "reminder_type"],
        )
    if index_exists("event_reminders", "idx_event_reminders_fire_at"):
        op.drop_index("idx_event_reminders_fire_at", table_name="event_reminders")
    if index_exists("event_reminders", "uq_event_reminders_event_type_day"):
        op.drop_index("uq_event_reminders_event_type_day", table_name="event_reminders")
    if column_exists("event_reminders", "day_total"):
        op.drop_column("event_reminders", "day_total")
    if column_exists("event_reminders", "day_index"):
        op.drop_column("event_reminders", "day_index")
    if column_exists("event_reminders", "occurrence_date"):
        op.drop_column("event_reminders", "occurrence_date")
