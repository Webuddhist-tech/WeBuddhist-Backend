from datetime import date, datetime, timezone
from typing import List, Optional
from uuid import UUID

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .event_reminder_model import EventReminder

# The per-day identity of a reminder. Named once so the two upsert paths and
# the index the migration creates cannot drift apart.
_OCCURRENCE_KEY = ["event_id", "reminder_type", "occurrence_date"]


def _reminder_values(
    event_id: UUID,
    reminder_type: str,
    fire_at: datetime,
    occurrence_date: date,
    day_index: Optional[int],
    day_total: Optional[int],
) -> dict:
    return {
        "event_id": event_id,
        "reminder_type": reminder_type,
        "fire_at": fire_at,
        "occurrence_date": occurrence_date,
        "day_index": day_index,
        "day_total": day_total,
        "sqs_message_id": None,
        "dispatched_at": None,
        "canceled_at": None,
        "created_at": datetime.now(timezone.utc),
    }


def create_or_replace_reminder(
    db: Session,
    event_id: UUID,
    reminder_type: str,
    fire_at: datetime,
    occurrence_date: date,
    day_index: Optional[int] = None,
    day_total: Optional[int] = None,
) -> None:
    """Upsert one occurrence-day's reminder, resetting its dispatch/cancel
    state so a rescheduled event gets a fresh reminder.

    Only for write paths that own the event's whole schedule (create, and
    rebuild-after-edit). The rolling materializer must not use this: it would
    reset dispatched_at on rows already sent and deliver them a second time -
    see insert_reminder_if_missing.

    Does not commit; callers own the transaction boundary so this can be
    composed atomically with other writes in the same session."""
    values = _reminder_values(
        event_id, reminder_type, fire_at, occurrence_date, day_index, day_total
    )
    stmt = insert(EventReminder).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=_OCCURRENCE_KEY,
        set_={
            "fire_at": fire_at,
            "day_index": day_index,
            "day_total": day_total,
            "sqs_message_id": None,
            "dispatched_at": None,
            "canceled_at": None,
        },
    )
    db.execute(stmt)


def insert_reminder_if_missing(
    db: Session,
    event_id: UUID,
    reminder_type: str,
    fire_at: datetime,
    occurrence_date: date,
    day_index: Optional[int] = None,
    day_total: Optional[int] = None,
) -> None:
    """Add an occurrence-day's reminder only if that day has none yet.

    The rolling materializer re-walks a recurring event's whole horizon on
    every run, so it revisits days it already wrote. DO NOTHING is what keeps
    that idempotent: an existing row keeps its dispatched_at and
    sqs_message_id, so a reminder already delivered is never resurrected.

    Does not commit; callers own the transaction boundary."""
    values = _reminder_values(
        event_id, reminder_type, fire_at, occurrence_date, day_index, day_total
    )
    stmt = insert(EventReminder).values(**values)
    stmt = stmt.on_conflict_do_nothing(index_elements=_OCCURRENCE_KEY)
    db.execute(stmt)


def clear_reminders_for_event(db: Session, event_id: UUID) -> None:
    """Delete every reminder row for the event, including one a concurrent
    dispatcher has already claimed.

    Deletion rather than a canceled_at stamp, because it is the stronger
    signal for both freshness checks in the pipeline: the dispatcher re-reads
    the row by id before sending (event_reminder_dispatch_service.
    _reminder_still_due) and the targets endpoint re-reads it by schedule
    (reminder_notification_service._reminder_superseded). A row that is gone
    fails both, exactly as a canceled one did.

    It also keeps the table from accumulating dead rows now that
    occurrence_date is part of a reminder's identity: a canceled row for a
    date the event no longer occupies would never be reused or removed. And
    it leaves the rebuild that follows with nothing to conflict against.

    Does not commit; callers own the transaction boundary so this can be
    composed atomically with the event write in the same session."""
    db.query(EventReminder).filter(
        EventReminder.event_id == event_id,
    ).delete(synchronize_session=False)


def list_due_reminders(db: Session, *, now: datetime, limit: int) -> List[EventReminder]:
    return (
        db.query(EventReminder)
        .filter(
            EventReminder.fire_at <= now,
            EventReminder.dispatched_at.is_(None),
            EventReminder.canceled_at.is_(None),
        )
        .order_by(EventReminder.fire_at.asc())
        .limit(limit)
        .all()
    )


def claim_reminder_for_dispatch(db: Session, reminder_id: UUID) -> bool:
    """Optimistically claim a reminder by stamping dispatched_at before the
    SQS send, so overlapping pollers don't double-enqueue. Returns True if
    this call won the claim."""
    now = datetime.now(timezone.utc)
    result = db.query(EventReminder).filter(
        EventReminder.id == reminder_id,
        EventReminder.dispatched_at.is_(None),
        EventReminder.canceled_at.is_(None),
    ).update({EventReminder.dispatched_at: now}, synchronize_session=False)
    db.commit()
    return result == 1


def mark_reminder_sqs_message_id(db: Session, reminder_id: UUID, sqs_message_id: str) -> None:
    db.query(EventReminder).filter(EventReminder.id == reminder_id).update(
        {EventReminder.sqs_message_id: sqs_message_id},
        synchronize_session=False,
    )
    db.commit()


def list_undispatched_reminders_missing_sqs_id(
    db: Session,
    *,
    older_than: datetime,
    limit: int,
) -> List[EventReminder]:
    """Reminders that were claimed (dispatched_at set) but never recorded an
    SQS MessageId - the commit-before-send crash window."""
    return (
        db.query(EventReminder)
        .filter(
            EventReminder.dispatched_at.isnot(None),
            EventReminder.dispatched_at <= older_than,
            EventReminder.sqs_message_id.is_(None),
            EventReminder.canceled_at.is_(None),
        )
        .order_by(EventReminder.dispatched_at.asc())
        .limit(limit)
        .all()
    )


def purge_reminders_before(db: Session, *, cutoff: datetime) -> int:
    """Drop reminders whose fire time is long past.

    A recurring series has no end, so its rows would otherwise grow without
    bound. Nothing reads a reminder after its fire time: the dispatcher and
    the reconciler both filter it out, and delivery idempotency lives in the
    worker's Redis keys rather than here. Commits, since the caller is a
    scheduled job owning no wider transaction."""
    deleted = db.query(EventReminder).filter(
        EventReminder.fire_at < cutoff,
    ).delete(synchronize_session=False)
    db.commit()
    return deleted


def get_event_reminder_for_schedule(
    db: Session,
    event_id: UUID,
    reminder_type: str,
    fire_at: datetime,
) -> Optional[EventReminder]:
    """The reminder row a given dispatch was queued for, or None if no row
    stands on that schedule any more.

    Resolved by fire_at rather than by (event_id, reminder_type) alone: an
    event now holds one row per occurrence-day, so the type no longer
    identifies a single row. fire_at does - two days of the same event cannot
    share a fire time - and it is the schedule the message was claimed
    against, so a row rebuilt onto a different schedule simply fails to
    match, which is the answer the caller wants.

    populate_existing() forces the row's current column values onto the
    returned object even if it's already in this session's identity map -
    without it, a second call in the same session (e.g. a freshness recheck
    against a row already loaded once) would silently hand back the first
    call's cached in-memory object instead of observing a concurrent
    update, since SQLAlchemy does not overwrite already-loaded attributes
    on a plain query by default."""
    return (
        db.query(EventReminder)
        .populate_existing()
        .filter(
            EventReminder.event_id == event_id,
            EventReminder.reminder_type == reminder_type,
            EventReminder.fire_at == fire_at,
        )
        .first()
    )


def get_reminder_by_id(db: Session, reminder_id: UUID) -> Optional[EventReminder]:
    return db.query(EventReminder).filter(EventReminder.id == reminder_id).first()
