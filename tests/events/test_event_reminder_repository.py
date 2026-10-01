"""get_event_reminder_for_schedule is called twice per request from the same
session (see reminder_notification_service._live_reminder's fail-fast +
authoritative recheck), with no commit on that session in between - so
expire_on_commit never fires to force a refresh. A plain SQLAlchemy query does
not otherwise overwrite an already identity-mapped object's attributes, so
without populate_existing(), the second call would silently hand back the
first call's cached in-memory object instead of observing a change committed
by a genuinely concurrent transaction (e.g. an event update's rebuild).
Only a real Session against a real engine can exercise the identity map, so
this uses an in-memory SQLite database (shared across two sessions via
StaticPool, to model two independent transactions) rather than mocks."""
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from pecha_api.events.event_reminder_model import EventReminder
from pecha_api.events.event_reminder_repository import (
    clear_reminders_for_event,
    get_event_reminder_for_schedule,
    purge_reminders_before,
)


def _make_sessionmaker():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    EventReminder.metadata.create_all(bind=engine, tables=[EventReminder.__table__])
    return sessionmaker(bind=engine)


def _reminder(
    *,
    event_id,
    fire_at,
    reminder_type="T_ZERO",
    occurrence_date=None,
    dispatched_at=None,
):
    return EventReminder(
        id=uuid4(),
        event_id=event_id,
        reminder_type=reminder_type,
        fire_at=fire_at,
        occurrence_date=occurrence_date or fire_at.date(),
        dispatched_at=dispatched_at,
        created_at=datetime.now(timezone.utc),
    )


def test_recheck_observes_a_cancellation_committed_by_a_concurrent_transaction():
    Session = _make_sessionmaker()
    setup_db = Session()
    event_id = uuid4()
    fire_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    setup_db.add(_reminder(event_id=event_id, fire_at=fire_at))
    setup_db.commit()
    setup_db.close()

    # This session plays the role of get_event_reminder_targets's own
    # session: it never commits between its two reads.
    reader_db = Session()
    first = get_event_reminder_for_schedule(reader_db, event_id, "T_ZERO", fire_at)
    assert first.canceled_at is None

    # A fully separate session/transaction - e.g. update_event_service
    # canceling this reminder while reader_db's request is still resolving
    # participants/devices.
    writer_db = Session()
    canceled_at = datetime.now(timezone.utc)
    writer_db.query(EventReminder).filter(EventReminder.event_id == event_id).update(
        {EventReminder.canceled_at: canceled_at}, synchronize_session=False,
    )
    writer_db.commit()
    writer_db.close()

    second = get_event_reminder_for_schedule(reader_db, event_id, "T_ZERO", fire_at)

    assert second is first  # identity map returns the same Python object...
    assert second.canceled_at is not None  # ...but populate_existing() refreshed it in place


def test_lookup_is_per_day_not_per_type():
    """An event holds one row per occurrence-day, so the type alone no longer
    names a row - only the schedule the dispatch was claimed against does."""
    Session = _make_sessionmaker()
    db = Session()
    event_id = uuid4()
    day_one = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    day_two = datetime(2026, 10, 2, 9, 0, tzinfo=timezone.utc)
    db.add(_reminder(event_id=event_id, fire_at=day_one))
    db.add(_reminder(event_id=event_id, fire_at=day_two))
    db.commit()

    first = get_event_reminder_for_schedule(db, event_id, "T_ZERO", day_one)
    second = get_event_reminder_for_schedule(db, event_id, "T_ZERO", day_two)

    assert first.occurrence_date == date(2026, 10, 1)
    assert second.occurrence_date == date(2026, 10, 2)
    assert first.id != second.id


def test_lookup_finds_nothing_once_the_event_moved_off_that_schedule():
    """A message queued for a day the event no longer occupies has to come
    back empty rather than matching some other day's row."""
    Session = _make_sessionmaker()
    db = Session()
    event_id = uuid4()
    fire_at = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    db.add(_reminder(event_id=event_id, fire_at=fire_at))
    db.commit()

    moved = fire_at + timedelta(hours=1)
    assert get_event_reminder_for_schedule(db, event_id, "T_ZERO", moved) is None


def test_clear_removes_every_row_including_claimed_ones():
    """A claimed row has to go too: the dispatcher re-reads it by id before
    sending, so a missing row stops that send just as a cancellation did,
    and leaving it behind would strand a dead date in the table forever."""
    Session = _make_sessionmaker()
    db = Session()
    event_id = uuid4()
    other_event_id = uuid4()
    fire_at = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc)
    db.add(_reminder(event_id=event_id, fire_at=fire_at))
    db.add(
        _reminder(
            event_id=event_id,
            fire_at=fire_at + timedelta(days=1),
            dispatched_at=datetime.now(timezone.utc),
        )
    )
    db.add(_reminder(event_id=other_event_id, fire_at=fire_at))
    db.commit()

    clear_reminders_for_event(db, event_id)
    db.commit()

    assert db.query(EventReminder).filter(EventReminder.event_id == event_id).count() == 0
    assert (
        db.query(EventReminder).filter(EventReminder.event_id == other_event_id).count() == 1
    )


def test_purge_drops_only_reminders_whose_moment_has_passed():
    Session = _make_sessionmaker()
    db = Session()
    event_id = uuid4()
    now = datetime.now(timezone.utc)
    db.add(_reminder(event_id=event_id, fire_at=now - timedelta(days=60)))
    db.add(_reminder(event_id=event_id, fire_at=now + timedelta(days=1)))
    db.commit()

    deleted = purge_reminders_before(db, cutoff=now - timedelta(days=30))

    assert deleted == 1
    assert db.query(EventReminder).count() == 1
