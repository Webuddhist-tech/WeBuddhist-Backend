"""Rebuild reminders for one-time events that already span several days.

Reminders are materialized when an event is written, so turning
EVENT_REMINDER_DAILY_ENABLED on changes nothing for events that already
exist: each keeps the single day-one pair it was created with until someone
happens to edit it. This walks the events that are owed more and rebuilds
them.

Run it once, after the flag is on. It is idempotent - each event is cleared
and rewritten from its current dates - so it is safe to re-run, and safe to
run again with the flag off to roll every event back to day one.

    python -m scripts.backfill_multi_day_event_reminders --dry-run
    python -m scripts.backfill_multi_day_event_reminders
"""
import argparse
import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from pecha_api.db.database import SessionLocal
from pecha_api.events.event_model import Event
from pecha_api.events.event_reminder_service import reschedule_event_reminders

logger = logging.getLogger("backfill_multi_day_event_reminders")

_PAGE_SIZE = 200


def _candidates(
    db: Session, *, after_id: UUID | None, limit: int
) -> tuple[list[Event], UUID | None]:
    """One-time events still to come whose end falls on a later day than
    their start.

    The day comparison is deliberately loose here - it uses UTC rather than
    each event's own zone - because this only decides which events are worth
    rebuilding. reschedule_event_reminders then applies the real per-event
    rule, so an event pulled in by the looser filter simply gets the same
    single day it already had.

    Returns the qualifying events *and* the id of the last row the database
    actually handed back, qualifying or not. The caller has to page on that
    second value: the limit applies to the raw page, before the single-day
    events are dropped, so a page of 200 that happens to hold no multi-day
    event yields an empty list while qualifying events still wait at higher
    ids. Paging on the filtered list would stop the scan there and leave
    every one of them with its original day-one reminders."""
    query = db.query(Event).filter(
        Event.is_recurring.is_(False),
        Event.end_date > datetime.now(timezone.utc),
    )
    if after_id is not None:
        query = query.filter(Event.id > after_id)
    rows = query.order_by(Event.id.asc()).limit(limit).all()
    if not rows:
        return [], None
    qualifying = [row for row in rows if row.end_date.date() > row.start_date.date()]
    return qualifying, rows[-1].id


def backfill(*, dry_run: bool, limit: int | None) -> int:
    processed = 0
    after_id = None

    while True:
        if limit is not None and processed >= limit:
            break

        with SessionLocal() as db:
            events, last_scanned_id = _candidates(db, after_id=after_id, limit=_PAGE_SIZE)
            # A None cursor is the only end of the scan - it means the page
            # came back empty, so there is nothing past it. An empty `events`
            # with a cursor is just a page of single-day events; advance and
            # keep walking.
            if last_scanned_id is None:
                break
            after_id = last_scanned_id

            if limit is not None:
                events = events[: limit - processed]

            for event in events:
                if dry_run:
                    logger.info(
                        "would rebuild reminders for event %s (%s -> %s)",
                        event.id,
                        event.start_date,
                        event.end_date,
                    )
                    processed += 1
                    continue
                try:
                    reschedule_event_reminders(db, event)
                    db.commit()
                    processed += 1
                    logger.info("rebuilt reminders for event %s", event.id)
                except Exception:
                    db.rollback()
                    logger.exception("failed to rebuild reminders for event %s", event.id)

    return processed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list the events that would be rebuilt without writing anything",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after this many events (default: all of them)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    count = backfill(dry_run=args.dry_run, limit=args.limit)
    verb = "would rebuild" if args.dry_run else "rebuilt"
    logger.info("%s %s multi-day event(s)", verb, count)


if __name__ == "__main__":
    main()
