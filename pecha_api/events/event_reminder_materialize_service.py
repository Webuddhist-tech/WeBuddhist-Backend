import logging
from datetime import datetime, timedelta, timezone

from pecha_api.config import get_int
from pecha_api.db.database import SessionLocal

from .event_reminder_repository import purge_reminders_before
from .event_reminder_service import (
    materialize_event_reminders,
    recurring_reminders_enabled,
)
from .event_repository import list_recurring_events_for_materialization

logger = logging.getLogger(__name__)


def materialize_recurring_event_reminders() -> int:
    """Top up reminders for every recurring event inside the rolling horizon.

    A recurrence rule has no end date, so its reminders cannot all be written
    when the event is saved. Instead each event's next `horizon` worth of
    occurrence-days is materialized here, and this job pushes that window
    forward as time passes.

    Writes are additive (see insert_reminder_if_missing): the job re-walks
    days it has already written on every run, and must leave those rows
    exactly as it found them - resetting one that has already been dispatched
    would deliver the same reminder a second time.

    Imminent reminders never depend on this job: creating or editing an event
    materializes its horizon immediately. Missing runs only stops the window
    advancing, so the schedule survives an outage shorter than the horizon.
    """
    if not recurring_reminders_enabled():
        return 0

    batch_size = max(get_int("EVENT_REMINDER_MATERIALIZE_BATCH_SIZE"), 1)
    now = datetime.now(timezone.utc)
    written = 0
    after_id = None

    while True:
        with SessionLocal() as db:
            events = list_recurring_events_for_materialization(
                db, after_id=after_id, limit=batch_size
            )
            if not events:
                break
            for event in events:
                # Per event, so one unexpandable rule (a lunar year with no
                # calendar file, say) costs its own reminders and not the
                # whole sweep's.
                try:
                    written += materialize_event_reminders(db, event, now=now)
                    db.commit()
                except Exception:
                    db.rollback()
                    logger.exception(
                        "Failed to materialize reminders for recurring event %s",
                        event.id,
                    )
            after_id = events[-1].id

    if written:
        logger.info("Materialized %s recurring event reminder(s)", written)
    return written


def purge_expired_event_reminders() -> int:
    """Sweep reminders whose fire time is long past.

    Recurring series would otherwise grow the table forever. Nothing reads a
    reminder once its moment has passed: both the dispatcher and the
    reconciler filter it out, and per-device delivery idempotency lives in
    the worker's Redis keys rather than in these rows."""
    retention_days = max(get_int("EVENT_REMINDER_RETENTION_DAYS"), 1)
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    with SessionLocal() as db:
        deleted = purge_reminders_before(db, cutoff=cutoff)

    if deleted:
        logger.info("Purged %s event reminder(s) older than %s", deleted, cutoff)
    return deleted
