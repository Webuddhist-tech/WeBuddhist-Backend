from datetime import date, datetime, timedelta, timezone
from unittest.mock import MagicMock
import pytest

from pecha_api.events.recurrence_service import (
    compute_initial_dates,
    expand_occurrences,
    resolve_next_occurrence,
)
from pecha_api.events.event_response_models import RecurrenceInput
from pecha_api.events.event_enums import RecurrenceFrequency, RecurrenceDateSystem


def _make_event(
    is_recurring=True,
    recurrence_frequency=None,
    recurrence_date_system=None,
    recurrence_calendar_type=None,
    recurrence_month=None,
    recurrence_day=None,
    recurrence_day_of_week=None,
    duration_days=1,
):
    """Create a mock event with recurrence attributes."""
    event = MagicMock()
    event.is_recurring = is_recurring
    event.recurrence_frequency = recurrence_frequency
    event.recurrence_date_system = recurrence_date_system
    event.recurrence_calendar_type = recurrence_calendar_type
    event.recurrence_month = recurrence_month
    event.recurrence_day = recurrence_day
    event.recurrence_day_of_week = recurrence_day_of_week
    event.duration_days = duration_days
    return event


class TestComputeInitialDates:
    def test_gregorian_yearly_computes_next_occurrence(self):
        recurrence = RecurrenceInput(
            frequency=RecurrenceFrequency.YEARLY,
            date_system=RecurrenceDateSystem.GREGORIAN,
            month=12,
            day=25,
            duration_days=1,
        )
        
        start_date, end_date = compute_initial_dates(recurrence)
        
        assert start_date.month == 12
        assert start_date.day == 25
        # compute_initial_dates works in whole days, so an occurrence today is
        # returned at 00:00 and is still valid. Compare dates, not timestamps.
        assert start_date.date() >= date.today()
        assert end_date == start_date

    def test_gregorian_monthly_computes_next_occurrence(self):
        recurrence = RecurrenceInput(
            frequency=RecurrenceFrequency.MONTHLY,
            date_system=RecurrenceDateSystem.GREGORIAN,
            day=15,
            duration_days=1,
        )
        
        start_date, end_date = compute_initial_dates(recurrence)
        
        assert start_date.day == 15
        # compute_initial_dates works in whole days, so an occurrence today is
        # returned at 00:00 and is still valid. Compare dates, not timestamps.
        assert start_date.date() >= date.today()

    def test_lunar_yearly_computes_next_occurrence(self):
        recurrence = RecurrenceInput(
            frequency=RecurrenceFrequency.YEARLY,
            date_system=RecurrenceDateSystem.TIBETAN_LUNAR,
            calendar_type="phugpa",
            month=4,
            day=15,
            duration_days=1,
        )
        
        start_date, end_date = compute_initial_dates(recurrence)
        
        # compute_initial_dates works in whole days, so an occurrence today is
        # returned at 00:00 and is still valid. Compare dates, not timestamps.
        assert start_date.date() >= date.today()
        assert end_date == start_date

    def test_lunar_monthly_computes_next_occurrence(self):
        recurrence = RecurrenceInput(
            frequency=RecurrenceFrequency.MONTHLY,
            date_system=RecurrenceDateSystem.TIBETAN_LUNAR,
            calendar_type="phugpa",
            day=15,
            duration_days=1,
        )
        
        start_date, end_date = compute_initial_dates(recurrence)
        
        # compute_initial_dates works in whole days, so an occurrence today is
        # returned at 00:00 and is still valid. Compare dates, not timestamps.
        assert start_date.date() >= date.today()

    def test_multi_day_duration(self):
        recurrence = RecurrenceInput(
            frequency=RecurrenceFrequency.YEARLY,
            date_system=RecurrenceDateSystem.GREGORIAN,
            month=1,
            day=1,
            duration_days=3,
        )

        start_date, end_date = compute_initial_dates(recurrence)

        assert (end_date - start_date).days == 2

    def test_gregorian_weekly_computes_next_occurrence(self):
        recurrence = RecurrenceInput(
            frequency=RecurrenceFrequency.WEEKLY,
            date_system=RecurrenceDateSystem.GREGORIAN,
            day_of_week=2,  # Wednesday
            duration_days=1,
        )

        start_date, end_date = compute_initial_dates(recurrence)

        assert start_date.weekday() == 2
        assert start_date.date() >= date.today()
        assert end_date == start_date


class TestExpandOccurrences:
    def test_gregorian_yearly_expands_multiple_years(self):
        event = _make_event(
            is_recurring=True,
            recurrence_frequency=RecurrenceFrequency.YEARLY.value,
            recurrence_date_system=RecurrenceDateSystem.GREGORIAN.value,
            recurrence_month=3,
            recurrence_day=15,
            duration_days=1,
        )
        
        occurrences = expand_occurrences(
            event,
            date(2024, 1, 1),
            date(2026, 12, 31),
        )
        
        assert len(occurrences) == 3
        assert occurrences[0][0] == date(2024, 3, 15)
        assert occurrences[1][0] == date(2025, 3, 15)
        assert occurrences[2][0] == date(2026, 3, 15)

    def test_gregorian_monthly_expands_within_year(self):
        event = _make_event(
            is_recurring=True,
            recurrence_frequency=RecurrenceFrequency.MONTHLY.value,
            recurrence_date_system=RecurrenceDateSystem.GREGORIAN.value,
            recurrence_day=15,
            duration_days=1,
        )
        
        occurrences = expand_occurrences(
            event,
            date(2025, 1, 1),
            date(2025, 3, 31),
        )
        
        assert len(occurrences) == 3
        assert occurrences[0][0] == date(2025, 1, 15)
        assert occurrences[1][0] == date(2025, 2, 15)
        assert occurrences[2][0] == date(2025, 3, 15)

    def test_lunar_yearly_expands(self):
        event = _make_event(
            is_recurring=True,
            recurrence_frequency=RecurrenceFrequency.YEARLY.value,
            recurrence_date_system=RecurrenceDateSystem.TIBETAN_LUNAR.value,
            recurrence_calendar_type="phugpa",
            recurrence_month=4,
            recurrence_day=15,
            duration_days=1,
        )
        
        occurrences = expand_occurrences(
            event,
            date(2024, 1, 1),
            date(2026, 12, 31),
        )
        
        assert len(occurrences) == 3
        for start_d, end_d in occurrences:
            assert start_d == end_d

    def test_lunar_monthly_expands(self):
        event = _make_event(
            is_recurring=True,
            recurrence_frequency=RecurrenceFrequency.MONTHLY.value,
            recurrence_date_system=RecurrenceDateSystem.TIBETAN_LUNAR.value,
            recurrence_calendar_type="phugpa",
            recurrence_day=15,
            duration_days=1,
        )
        
        occurrences = expand_occurrences(
            event,
            date(2025, 1, 1),
            date(2025, 12, 31),
        )
        
        # Tibetan lunar calendar may have 10-13 months per Gregorian year
        # depending on leap months and calendar alignment
        assert len(occurrences) >= 10

    def test_multi_day_duration_in_expansion(self):
        event = _make_event(
            is_recurring=True,
            recurrence_frequency=RecurrenceFrequency.YEARLY.value,
            recurrence_date_system=RecurrenceDateSystem.GREGORIAN.value,
            recurrence_month=1,
            recurrence_day=1,
            duration_days=3,
        )
        
        occurrences = expand_occurrences(
            event,
            date(2025, 1, 1),
            date(2025, 12, 31),
        )
        
        assert len(occurrences) == 1
        start_d, end_d = occurrences[0]
        assert (end_d - start_d).days == 2

    def test_skips_invalid_dates(self):
        event = _make_event(
            is_recurring=True,
            recurrence_frequency=RecurrenceFrequency.YEARLY.value,
            recurrence_date_system=RecurrenceDateSystem.GREGORIAN.value,
            recurrence_month=2,
            recurrence_day=30,
            duration_days=1,
        )
        
        occurrences = expand_occurrences(
            event,
            date(2024, 1, 1),
            date(2026, 12, 31),
        )
        
        assert len(occurrences) == 0

    def test_gregorian_weekly_expands_every_week(self):
        event = _make_event(
            is_recurring=True,
            recurrence_frequency=RecurrenceFrequency.WEEKLY.value,
            recurrence_date_system=RecurrenceDateSystem.GREGORIAN.value,
            recurrence_day_of_week=0,  # Monday
            duration_days=1,
        )

        occurrences = expand_occurrences(
            event,
            date(2025, 1, 1),  # Wednesday
            date(2025, 1, 31),
        )

        assert [start_d.weekday() for start_d, _ in occurrences] == [0] * len(occurrences)
        assert occurrences[0][0] == date(2025, 1, 6)
        assert occurrences[-1][0] == date(2025, 1, 27)

    def test_non_recurring_event_returns_empty(self):
        event = _make_event(
            is_recurring=False,
        )
        
        occurrences = expand_occurrences(
            event,
            date(2025, 1, 1),
            date(2025, 12, 31),
        )
        
        assert occurrences == []


class TestResolveNextOccurrence:
    def test_finds_next_gregorian_yearly_occurrence(self):
        event = _make_event(
            is_recurring=True,
            recurrence_frequency=RecurrenceFrequency.YEARLY.value,
            recurrence_date_system=RecurrenceDateSystem.GREGORIAN.value,
            recurrence_month=12,
            recurrence_day=25,
            duration_days=1,
        )
        
        next_date = resolve_next_occurrence(event, after=date(2025, 1, 1))
        
        assert next_date is not None
        assert next_date.month == 12
        assert next_date.day == 25
        assert next_date.year >= 2025

    def test_finds_next_gregorian_monthly_occurrence(self):
        event = _make_event(
            is_recurring=True,
            recurrence_frequency=RecurrenceFrequency.MONTHLY.value,
            recurrence_date_system=RecurrenceDateSystem.GREGORIAN.value,
            recurrence_day=15,
            duration_days=1,
        )
        
        next_date = resolve_next_occurrence(event, after=date(2025, 3, 20))
        
        assert next_date is not None
        assert next_date.day == 15
        assert next_date >= date(2025, 4, 1)

    def test_finds_next_gregorian_weekly_occurrence(self):
        event = _make_event(
            is_recurring=True,
            recurrence_frequency=RecurrenceFrequency.WEEKLY.value,
            recurrence_date_system=RecurrenceDateSystem.GREGORIAN.value,
            recurrence_day_of_week=4,  # Friday
            duration_days=1,
        )

        next_date = resolve_next_occurrence(event, after=date(2025, 3, 20))  # Thursday

        assert next_date is not None
        assert next_date.weekday() == 4
        assert next_date == date(2025, 3, 21)

    def test_non_recurring_event_returns_none(self):
        event = _make_event(
            is_recurring=False,
        )
        
        next_date = resolve_next_occurrence(event)
        
        assert next_date is None
