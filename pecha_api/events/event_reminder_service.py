import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Iterator, List, Optional, Sequence, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from pecha_api.config import get, get_int
from pecha_api.timezone_utils import TimezoneInfo

from .event_model import Event
from .event_reminder_repository import (
    clear_reminders_for_event,
    create_or_replace_reminder,
    insert_reminder_if_missing,
)
from .recurrence_service import (
    combine_date_with_time_of_day,
    combine_occurrence_window,
    expand_occurrences,
)

logger = logging.getLogger(__name__)

REMINDER_TYPE_T_MINUS_10 = "T_MINUS_10"
REMINDER_TYPE_T_ZERO = "T_ZERO"

_TRUTHY = {"1", "true", "yes"}


def _minutes_before() -> int:
    return max(get_int("EVENT_REMINDER_MINUTES_BEFORE"), 1)


def _horizon_days() -> int:
    return max(get_int("EVENT_REMINDER_HORIZON_DAYS"), 1)


def _daily_enabled() -> bool:
    """Per-day reminders for a one-time event that spans several days."""
    return get("EVENT_REMINDER_DAILY_ENABLED").lower() in _TRUTHY


def recurring_reminders_enabled() -> bool:
    """Reminders for recurring events at all - they had none before."""
    return get("EVENT_REMINDER_RECURRING_ENABLED").lower() in _TRUTHY


def _safe_timezone(timezone_name: Optional[str], *, event_id: Optional[UUID]) -> TimezoneInfo:
    """Resolve an event's timezone, falling back to UTC instead of raising.

    timezone_utils._resolve_timezone raises an HTTPException on a name it
    does not know, which cannot be allowed here: scheduling runs inside the
    event's own transaction (see event_service's after_flush hook), so a
    raise would roll back the event itself. A reminder an hour off is a far
    better failure than an event that cannot be saved, so an unusable zone
    degrades to UTC and says so in the log.

    Names are validated on write by normalize_timezone_name, so this only
    catches rows that predate that validation."""
    if not timezone_name or not timezone_name.strip():
        return timezone.utc
    cleaned = timezone_name.strip()
    if cleaned.upper() == "UTC":
        return timezone.utc
    try:
        return ZoneInfo(cleaned)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning(
            "Event %s has unusable timezone %r; scheduling reminders in UTC",
            event_id,
            timezone_name,
        )
        return timezone.utc


def _as_utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


@dataclass(frozen=True)
class OccurrenceDay:
    """One day a set of reminders is owed for.

    occurrence_date is the local calendar date the day *starts* on, which is
    not always the date its T-minus reminder fires on: a start just after
    midnight puts the warning on the previous day."""

    occurrence_date: date
    start_at: datetime
    day_index: Optional[int] = None
    day_total: Optional[int] = None


def _numbered(days: Sequence[Tuple[date, datetime]]) -> List[OccurrenceDay]:
    """Attach 1-based day numbering, but only to a run worth numbering.

    A single-day occurrence leaves both fields None, which is what keeps its
    push copy identical to what it has always been."""
    total = len(days)
    if total == 1:
        occurrence_date, start_at = days[0]
        return [OccurrenceDay(occurrence_date=occurrence_date, start_at=start_at)]
    return [
        OccurrenceDay(
            occurrence_date=occurrence_date,
            start_at=start_at,
            day_index=index,
            day_total=total,
        )
        for index, (occurrence_date, start_at) in enumerate(days, start=1)
    ]


def _one_time_days(event: Event) -> List[OccurrenceDay]:
    """Every day of a one-time event, at the same local wall-clock time.

    Local rather than a flat 24 hours so a 09:00 event stays at 09:00 across
    a DST shift, which is the time its attendees have in mind.

    A day counts only while its start falls strictly before the event's end.
    That is what separates a real multi-day event (day 5 at 09:00, ending
    17:00, still inside) from one evening that happens to cross midnight
    (20:00 Sept 23 to 02:00 Sept 24), which would otherwise be handed a
    second day of reminders 18 hours after everyone went home."""
    start_date = _as_utc(event.start_date)
    end_date = _as_utc(event.end_date)
    tz = _safe_timezone(event.timezone, event_id=event.id)
    local_start = start_date.astimezone(tz)
    time_of_day = local_start.time()

    days: List[Tuple[date, datetime]] = [(local_start.date(), start_date)]
    if _daily_enabled():
        local_date = local_start.date()
        while True:
            local_date += timedelta(days=1)
            start_at = datetime.combine(local_date, time_of_day, tzinfo=tz).astimezone(
                timezone.utc
            )
            if start_at >= end_date:
                break
            days.append((local_date, start_at))
    return _numbered(days)


def _recurring_days(event: Event, *, today: date) -> List[OccurrenceDay]:
    """Every day of every occurrence inside the rolling horizon.

    Deliberately *not* the local wall-clock rule used for one-time events.
    Occurrence expansion is UTC-anchored (recurrence_service.
    combine_date_with_time_of_day), so the instant the app shows for an
    occurrence is the template's UTC time-of-day on that date. Computing
    reminders in local time would drift an hour away from the displayed
    start after a DST shift, and a reminder that disagrees with the time on
    screen is worse than the drift itself. That drift lives in occurrence
    expansion and has to be fixed there, for every read path at once."""
    horizon_end = today + timedelta(days=_horizon_days())
    template_start = _as_utc(event.start_date)
    template_end = _as_utc(event.end_date)

    result: List[OccurrenceDay] = []
    for start_d, end_d in expand_occurrences(event, today, horizon_end):
        occurrence_start, occurrence_end = combine_occurrence_window(
            start_d, end_d, template_start, template_end
        )
        days: List[Tuple[date, datetime]] = [(start_d, occurrence_start)]
        local_date = start_d
        while local_date < end_d:
            local_date += timedelta(days=1)
            start_at = combine_date_with_time_of_day(local_date, template_start)
            if start_at >= occurrence_end:
                break
            days.append((local_date, start_at))
        result.extend(_numbered(days))
    return result


def _reminder_types(event: Event) -> List[str]:
    """A recurring series sends the warning only.

    It repeats for as long as the event exists and there is no per-occurrence
    way to decline it, so the second push - "Starting now", ten minutes after
    "Starting in 10 minutes" - buys little against the fatigue it adds."""
    if event.is_recurring:
        return [REMINDER_TYPE_T_MINUS_10]
    return [REMINDER_TYPE_T_MINUS_10, REMINDER_TYPE_T_ZERO]


def _reminder_rows(
    event: Event, *, now: datetime
) -> Iterator[Tuple[str, datetime, date, Optional[int], Optional[int]]]:
    """Every reminder the event is owed from `now` forward.

    Rows already in the past are skipped rather than written: they would fire
    immediately on the next dispatch poll, which for an event created or
    edited mid-run means notifying people about days that already happened."""
    # The organizer's switch, checked before anything is computed: turning it
    # off and rebuilding is what actually withdraws a scheduled reminder,
    # since the rebuild clears the old rows and writes none back.
    if not getattr(event, "notifications_enabled", True):
        return

    if event.is_recurring:
        if not recurring_reminders_enabled():
            return
        days = _recurring_days(event, today=now.astimezone(timezone.utc).date())
    else:
        days = _one_time_days(event)

    minutes = _minutes_before()
    for day in days:
        for reminder_type in _reminder_types(event):
            fire_at = (
                day.start_at - timedelta(minutes=minutes)
                if reminder_type == REMINDER_TYPE_T_MINUS_10
                else day.start_at
            )
            if fire_at <= now:
                continue
            yield (
                reminder_type,
                fire_at,
                day.occurrence_date,
                day.day_index,
                day.day_total,
            )


def schedule_event_reminders(db: Session, event: Event, *, now: Optional[datetime] = None) -> None:
    """Write the reminders a freshly created event is owed.

    Does not commit; the caller owns the transaction boundary so this can be
    composed atomically with the event write in the same session."""
    now = now or datetime.now(timezone.utc)
    for reminder_type, fire_at, occurrence_date, day_index, day_total in _reminder_rows(
        event, now=now
    ):
        create_or_replace_reminder(
            db,
            event.id,
            reminder_type,
            fire_at,
            occurrence_date,
            day_index=day_index,
            day_total=day_total,
        )


def reschedule_event_reminders(db: Session, event: Event, *, now: Optional[datetime] = None) -> None:
    """Rebuild an event's reminders after its schedule changed.

    Every existing row goes first, so a day the event no longer occupies
    cannot survive the rebuild and fire on its own.

    Does not commit; the caller owns the transaction boundary."""
    clear_reminders_for_event(db, event.id)
    schedule_event_reminders(db, event, now=now)


def clear_event_reminders(db: Session, event_id: UUID) -> None:
    """Drop every pending reminder, e.g. because the event was deleted or is
    no longer eligible for reminders at all.

    Does not commit; the caller owns the transaction boundary."""
    clear_reminders_for_event(db, event_id)


def materialize_event_reminders(
    db: Session, event: Event, *, now: Optional[datetime] = None
) -> int:
    """Top up an event's reminders as the rolling horizon advances.

    Additive by construction: it re-walks days it has already written, so it
    inserts only what is missing and never touches an existing row. Using the
    replacing write here would reset dispatched_at on reminders already sent
    and deliver them again on the next poll.

    Does not commit; the caller owns the transaction boundary."""
    now = now or datetime.now(timezone.utc)
    written = 0
    for reminder_type, fire_at, occurrence_date, day_index, day_total in _reminder_rows(
        event, now=now
    ):
        insert_reminder_if_missing(
            db,
            event.id,
            reminder_type,
            fire_at,
            occurrence_date,
            day_index=day_index,
            day_total=day_total,
        )
        written += 1
    return written
