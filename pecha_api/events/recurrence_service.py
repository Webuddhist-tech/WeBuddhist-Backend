from datetime import date, datetime, timedelta, timezone
from typing import Optional
from calendar import monthrange

from pecha_api.calendar.calendar_parser import (
    CalendarType,
    find_gregorian_dates_for_lunar,
)
from .event_model import Event
from .event_response_models import RecurrenceInput
from .event_enums import RecurrenceFrequency, RecurrenceDateSystem


def _date_to_datetime_utc(d: date) -> datetime:
    """Convert date to datetime at midnight UTC."""
    return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)


def combine_date_with_time_of_day(occurrence_date: date, reference: datetime) -> datetime:
    """
    Apply the wall-clock time-of-day carried by `reference` onto `occurrence_date`.

    A recurring event's rule only pins a day/month, not a time of day, so the
    time has to come from elsewhere: the datetime the client sent alongside
    the rule (create/update), or the template event's own stored start/end
    when expanding future occurrences for a listing. `reference` is
    normalized to UTC first since Event.start_date/end_date are always
    persisted in UTC.
    """
    reference_utc = (
        reference.astimezone(timezone.utc)
        if reference.tzinfo is not None
        else reference.replace(tzinfo=timezone.utc)
    )
    return datetime(
        occurrence_date.year,
        occurrence_date.month,
        occurrence_date.day,
        reference_utc.hour,
        reference_utc.minute,
        reference_utc.second,
        reference_utc.microsecond,
        tzinfo=timezone.utc,
    )


def combine_occurrence_window(
    start_d: date, end_d: date, template_start: datetime, template_end: datetime
) -> tuple[datetime, datetime]:
    """Combine an occurrence's calendar dates with the template's time-of-day.

    Write-time validation (see `_validate_date_range` calls in event_service)
    rejects new templates whose start/end time-of-day would invert a one-day
    (start_d == end_d) occurrence, but that guard can't fix templates that
    were already persisted before it existed. Clamping end to start here
    keeps every read path (event lists, featured events, group feeds) from
    ever surfacing end_date < start_date, regardless of how the underlying
    row got into that state.
    """
    occurrence_start = combine_date_with_time_of_day(start_d, template_start)
    occurrence_end = combine_date_with_time_of_day(end_d, template_end)
    if occurrence_end < occurrence_start:
        occurrence_end = occurrence_start
    return occurrence_start, occurrence_end


def _resolve_gregorian_yearly(
    month: int,
    day: int,
    from_date: date,
    to_date: date,
) -> list[date]:
    """Find all occurrences of a Gregorian month/day in the date range."""
    occurrences = []
    
    for year in range(from_date.year, to_date.year + 1):
        try:
            occurrence = date(year, month, day)
            if from_date <= occurrence <= to_date:
                occurrences.append(occurrence)
        except ValueError:
            continue
    
    return occurrences


def _resolve_gregorian_monthly(
    day: int,
    from_date: date,
    to_date: date,
) -> list[date]:
    """Find all occurrences of a Gregorian day in each month within the date range."""
    occurrences = []
    
    current = date(from_date.year, from_date.month, 1)
    end = date(to_date.year, to_date.month, monthrange(to_date.year, to_date.month)[1])
    
    while current <= end:
        _, max_day = monthrange(current.year, current.month)
        if day <= max_day:
            occurrence = date(current.year, current.month, day)
            if from_date <= occurrence <= to_date:
                occurrences.append(occurrence)
        
        if current.month == 12:
            current = date(current.year + 1, 1, 1)
        else:
            current = date(current.year, current.month + 1, 1)
    
    return occurrences


def _resolve_gregorian_weekly(
    day_of_week: int,
    from_date: date,
    to_date: date,
) -> list[date]:
    """Find all occurrences of a given weekday (0=Monday..6=Sunday) in the date range."""
    occurrences = []

    days_ahead = (day_of_week - from_date.weekday()) % 7
    current = from_date + timedelta(days=days_ahead)

    while current <= to_date:
        occurrences.append(current)
        current += timedelta(days=7)

    return occurrences


def _resolve_lunar_yearly(
    month: int,
    day: int,
    calendar_type: str,
    from_date: date,
    to_date: date,
) -> list[date]:
    """Find all occurrences of a lunar month/day in the date range."""
    cal_type = CalendarType.PHUGPA if calendar_type == "phugpa" else CalendarType.TSURPHU
    
    occurrences = find_gregorian_dates_for_lunar(
        lunar_month=month,
        lunar_day=day,
        calendar_type=cal_type,
        gregorian_year_start=from_date.year,
        gregorian_year_end=to_date.year,
    )
    return [d for d in occurrences if from_date <= d <= to_date]


def _resolve_lunar_monthly(
    day: int,
    calendar_type: str,
    from_date: date,
    to_date: date,
) -> list[date]:
    """Find all occurrences of a lunar day across all months in the date range."""
    cal_type = CalendarType.PHUGPA if calendar_type == "phugpa" else CalendarType.TSURPHU
    all_occurrences = []
    
    for month in range(1, 13):
        occurrences = find_gregorian_dates_for_lunar(
            lunar_month=month,
            lunar_day=day,
            calendar_type=cal_type,
            gregorian_year_start=from_date.year,
            gregorian_year_end=to_date.year,
        )
        all_occurrences.extend(occurrences)
    
    return sorted([d for d in all_occurrences if from_date <= d <= to_date])


def resolve_next_occurrence(event: Event, after: Optional[date] = None) -> Optional[date]:
    """
    Return the next upcoming occurrence date for a recurring event.
    
    For active multi-day occurrences (started before `after` but still ongoing),
    this returns the start date of the *next* occurrence that starts on or after
    `after`, not the currently active one. Use `resolve_current_or_next_occurrence`
    if you need to include active occurrences.
    
    Args:
        event: The recurring event
        after: Find occurrence starting on or after this date (default: today)
    
    Returns:
        Next occurrence start date or None if no future occurrences
    """
    if not event.is_recurring:
        return None
    
    if after is None:
        after = date.today()
    
    # Use 5-year horizon to guarantee coverage of leap-day (Feb 29) recurrences,
    # which occur every 4 years
    search_end = date(after.year + 5, 12, 31)
    
    occurrences = expand_occurrences(event, after, search_end)
    
    # Return the first occurrence that starts on or after `after`
    for start_d, end_d in occurrences:
        if start_d >= after:
            return start_d
    
    return None


def resolve_current_or_next_occurrence(
    event: Event, after: Optional[date] = None
) -> Optional[tuple[date, date, bool]]:
    """
    Return the current (active) or next upcoming occurrence for a recurring event.
    
    Args:
        event: The recurring event
        after: Reference date (default: today)
    
    Returns:
        Tuple of (start_date, end_date, is_active) or None if no occurrence found.
        is_active is True if the occurrence started before `after` but is still ongoing.
    """
    if not event.is_recurring:
        return None
    
    if after is None:
        after = date.today()
    
    search_end = date(after.year + 5, 12, 31)
    occurrences = expand_occurrences(event, after, search_end)
    
    for start_d, end_d in occurrences:
        if end_d >= after:
            is_active = start_d < after
            return (start_d, end_d, is_active)
    
    return None


def expand_occurrences(
    event: Event,
    from_date: date,
    to_date: date,
) -> list[tuple[date, date]]:
    """
    Return list of (start_date, end_date) tuples for occurrences in range.
    
    Args:
        event: The recurring event
        from_date: Start of date range
        to_date: End of date range
    
    Returns:
        List of (start_date, end_date) tuples, sorted chronologically
    """
    if not event.is_recurring:
        return []
    
    frequency = event.recurrence_frequency
    date_system = event.recurrence_date_system
    day = event.recurrence_day
    day_of_week = event.recurrence_day_of_week
    month = event.recurrence_month
    calendar_type = event.recurrence_calendar_type
    duration = event.duration_days

    # Expand search window backwards to capture multi-day occurrences that
    # started before from_date but are still active within the window
    search_from = from_date - timedelta(days=duration - 1) if duration > 1 else from_date

    if frequency == RecurrenceFrequency.WEEKLY.value:
        occurrence_dates = _resolve_gregorian_weekly(day_of_week, search_from, to_date)
    elif frequency == RecurrenceFrequency.YEARLY.value:
        if date_system == RecurrenceDateSystem.GREGORIAN.value:
            occurrence_dates = _resolve_gregorian_yearly(month, day, search_from, to_date)
        else:
            occurrence_dates = _resolve_lunar_yearly(month, day, calendar_type, search_from, to_date)
    else:
        if date_system == RecurrenceDateSystem.GREGORIAN.value:
            occurrence_dates = _resolve_gregorian_monthly(day, search_from, to_date)
        else:
            occurrence_dates = _resolve_lunar_monthly(day, calendar_type, search_from, to_date)
    
    # Build (start, end) tuples and filter to those overlapping the requested window
    results = []
    for d in occurrence_dates:
        end_d = d + timedelta(days=duration - 1)
        # Include if occurrence overlaps with [from_date, to_date]
        if end_d >= from_date and d <= to_date:
            results.append((d, end_d))
    
    return results


def compute_initial_dates(recurrence: RecurrenceInput) -> tuple[datetime, datetime]:
    """
    Compute start_date/end_date for a new recurring event (next occurrence).
    
    Args:
        recurrence: Recurrence rule
    
    Returns:
        Tuple of (start_date, end_date) as datetime objects
    """
    today = date.today()
    # Use 5-year horizon to guarantee coverage of leap-day (Feb 29) recurrences
    search_end = date(today.year + 5, 12, 31)
    
    if recurrence.frequency == RecurrenceFrequency.WEEKLY:
        occurrences = _resolve_gregorian_weekly(
            recurrence.day_of_week,
            today,
            search_end,
        )
    elif recurrence.frequency == RecurrenceFrequency.YEARLY:
        if recurrence.date_system == RecurrenceDateSystem.GREGORIAN:
            occurrences = _resolve_gregorian_yearly(
                recurrence.month,
                recurrence.day,
                today,
                search_end,
            )
        else:
            occurrences = _resolve_lunar_yearly(
                recurrence.month,
                recurrence.day,
                recurrence.calendar_type,
                today,
                search_end,
            )
    else:
        if recurrence.date_system == RecurrenceDateSystem.GREGORIAN:
            occurrences = _resolve_gregorian_monthly(
                recurrence.day,
                today,
                search_end,
            )
        else:
            occurrences = _resolve_lunar_monthly(
                recurrence.day,
                recurrence.calendar_type,
                today,
                search_end,
            )
    
    if not occurrences:
        raise ValueError("No future occurrences found for this recurrence rule")
    
    start_date = occurrences[0]
    end_date = start_date + timedelta(days=recurrence.duration_days - 1)
    
    return _date_to_datetime_utc(start_date), _date_to_datetime_utc(end_date)
