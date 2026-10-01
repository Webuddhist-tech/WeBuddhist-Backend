"""Regression check: recurring events keep the time-of-day the client sent,
instead of always landing on midnight."""
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.events.event_response_models import RecurrenceInput, UpdateEventRequest
from pecha_api.events.event_service import update_event_service
from pecha_api.events.recurrence_service import (
    combine_date_with_time_of_day,
    combine_occurrence_window,
)

client = TestClient(api)
M = "pecha_api.events.event_service"
R = "pecha_api.events.recurrence_service"
AUTH = {"Authorization": "Bearer token"}
GROUP = str(uuid4())


class _FixedToday(date):
    """`date` with today() pinned, for patching into recurrence_service.

    Recurrence resolution starts from date.today() and returns the next
    occurrence on or after it, so a test asserting a concrete resolved date
    has to pin today - otherwise the assertion quietly changes meaning once
    the real calendar moves past the date it hardcoded."""

    _TODAY = date(2026, 9, 1)

    @classmethod
    def today(cls) -> date:
        return cls._TODAY


def test_combine_date_with_time_of_day_applies_utc_time_to_new_date():
    occurrence = date(2027, 3, 10)
    reference = datetime(2020, 1, 1, 9, 30, 0, tzinfo=timezone.utc)
    result = combine_date_with_time_of_day(occurrence, reference)
    assert result == datetime(2027, 3, 10, 9, 30, 0, tzinfo=timezone.utc)


def test_combine_date_with_time_of_day_normalizes_non_utc_reference():
    occurrence = date(2027, 3, 10)
    # +05:30 (IST) 15:00 == 09:30 UTC
    reference = datetime(2020, 1, 1, 15, 0, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
    result = combine_date_with_time_of_day(occurrence, reference)
    assert result == datetime(2027, 3, 10, 9, 30, 0, tzinfo=timezone.utc)


def _row(ev, md):
    return SimpleNamespace(
        id=uuid4(), plan_id=None, accumulator_id=None, mantra_id=None, timer_id=None,
        group_recitation_collection_id=None, group_id=ev.group_id, location_id=None,
        location=None, start_date=ev.start_date, end_date=ev.end_date, image_url=None,
        featured=False, event_format=ev.event_format, is_recurring=bool(ev.is_recurring),
        recurrence_frequency=ev.recurrence_frequency,
        recurrence_date_system=ev.recurrence_date_system,
        recurrence_calendar_type=ev.recurrence_calendar_type,
        recurrence_month=ev.recurrence_month, recurrence_day=ev.recurrence_day,
        recurrence_day_of_week=ev.recurrence_day_of_week,
        duration_days=ev.duration_days,
        metadata_entries=[SimpleNamespace(id=uuid4(), name=m.name,
                                          description=m.description, language=m.language)
                          for m in md],
        links=[], created_at=datetime.now(timezone.utc),
        created_by=ev.created_by, updated_at=None,
    )


def _post(payload):
    with patch(f"{M}.validate_cms_author_details",
               return_value=SimpleNamespace(id=uuid4(), email="a@e.com")), \
         patch(f"{M}.require_can_create_content"), patch(f"{M}.SessionLocal"), \
         patch(f"{M}.enqueue_event_notification"), \
         patch(
             f"{M}.save_event",
             side_effect=lambda db, e, md, li=None, **_kwargs: _row(e, md),
         ):
        return client.post("/cms/events", json=payload, headers=AUTH)


def test_create_recurring_event_keeps_the_sent_time_of_day():
    payload = {
        "group_id": GROUP,
        "metadata": [{"name": "Monthly Tsok", "language": "EN"}],
        "start_date": "2026-09-13T09:30:00Z",
        "end_date": "2026-09-13T17:00:00Z",
        "recurrence": {"frequency": "MONTHLY", "date_system": "GREGORIAN",
                       "day": 10, "duration_days": 1},
    }
    response = _post(payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["start_date"].endswith("T09:30:00Z"), body["start_date"]
    assert body["end_date"].endswith("T17:00:00Z"), body["end_date"]


def test_create_recurring_event_without_times_still_defaults_to_midnight():
    payload = {
        "group_id": GROUP,
        "metadata": [{"name": "Monthly Tsok", "language": "EN"}],
        "recurrence": {"frequency": "MONTHLY", "date_system": "GREGORIAN",
                       "day": 10, "duration_days": 1},
    }
    response = _post(payload)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["start_date"].endswith("T00:00:00Z"), body["start_date"]


def test_create_recurring_event_rejects_inverted_one_day_time_window():
    """duration_days == 1 pins start/end to the same calendar day, so an end
    time before the start time can never be a valid occurrence."""
    payload = {
        "group_id": GROUP,
        "metadata": [{"name": "Monthly Tsok", "language": "EN"}],
        "start_date": "2026-09-13T17:00:00Z",
        "end_date": "2026-09-13T09:30:00Z",
        "recurrence": {"frequency": "MONTHLY", "date_system": "GREGORIAN",
                       "day": 10, "duration_days": 1},
    }
    with pytest.raises(ValueError, match="end_date must be greater than or equal"):
        _post(payload)


# ------------------------- update: preserving time-of-day -------------------------


def _timed_recurring_event_stub() -> SimpleNamespace:
    """A previously-created recurring event with a real (non-midnight) time
    window, as if created via the fixed create_event_service path above."""
    return SimpleNamespace(
        id=uuid4(), group_id=uuid4(), plan_id=None, accumulator_id=None,
        mantra_id=None, timer_id=None, group_recitation_collection_id=None,
        location_id=None, location=None, timezone="UTC", image_url=None,
        featured=False, event_format="hybrid", created_by="a@e.com",
        created_at=datetime.now(timezone.utc), updated_at=None,
        is_recurring=True,
        recurrence_frequency="MONTHLY", recurrence_date_system="GREGORIAN",
        recurrence_calendar_type=None, recurrence_month=None, recurrence_day=10,
        recurrence_day_of_week=None,
        duration_days=1,
        start_date=datetime(2026, 9, 10, 9, 30, 0, tzinfo=timezone.utc),
        end_date=datetime(2026, 9, 10, 17, 0, 0, tzinfo=timezone.utc),
        metadata_entries=[], links=[],
    )


def test_update_recurring_event_without_times_keeps_existing_time_of_day():
    """Regression for: updating a recurring event's rule (e.g. changing the
    day) without resending start/end times used to reset the event to
    midnight instead of keeping its existing 09:30/17:00 window."""
    existing = _timed_recurring_event_stub()
    request = UpdateEventRequest(
        recurrence=RecurrenceInput(
            frequency="MONTHLY", date_system="GREGORIAN", day=15, duration_days=1,
        )
    )
    assert request.start_date is None and request.end_date is None

    # today is pinned so the resolved occurrence is 2026-09-15 whatever the
    # real calendar date is.
    with patch(f"{R}.date", _FixedToday), \
         patch(f"{M}.validate_cms_author_details",
               return_value=SimpleNamespace(id=uuid4(), email="a@e.com")), \
         patch(f"{M}._require_can_edit_event"), patch(f"{M}.SessionLocal"), \
         patch(f"{M}.get_event_by_id", return_value=existing), \
         patch(f"{M}.update_event", side_effect=lambda db, event, **kw: event), \
         patch(f"{M}._sync_event_reminders"):
        result = update_event_service(token="token", event_id=existing.id, request=request)

    assert result.start_date.time() == datetime(2026, 9, 15, 9, 30).time()
    assert result.end_date.time() == datetime(2026, 9, 15, 17, 0).time()
    assert result.start_date.date() == date(2026, 9, 15)


def test_update_recurring_event_rejects_inverted_one_day_time_window():
    existing = _timed_recurring_event_stub()
    request = UpdateEventRequest(
        recurrence=RecurrenceInput(
            frequency="MONTHLY", date_system="GREGORIAN", day=10, duration_days=1,
        ),
        start_date=datetime(2026, 10, 10, 17, 0, tzinfo=timezone.utc),
        end_date=datetime(2026, 10, 10, 9, 30, tzinfo=timezone.utc),
    )

    with patch(f"{M}.validate_cms_author_details",
               return_value=SimpleNamespace(id=uuid4(), email="a@e.com")), \
         patch(f"{M}._require_can_edit_event"), patch(f"{M}.SessionLocal"), \
         patch(f"{M}.get_event_by_id", return_value=existing):
        with pytest.raises(ValueError, match="end_date must be greater than or equal"):
            update_event_service(token="token", event_id=existing.id, request=request)


# ------------------------- occurrence expansion: no inverted ranges -------------------------


def test_combine_occurrence_window_preserves_a_normal_range():
    start_d, end_d = date(2026, 10, 10), date(2026, 10, 10)
    template_start = datetime(2020, 1, 1, 9, 30, tzinfo=timezone.utc)
    template_end = datetime(2020, 1, 1, 17, 0, tzinfo=timezone.utc)

    occurrence_start, occurrence_end = combine_occurrence_window(
        start_d, end_d, template_start, template_end
    )

    assert occurrence_start == datetime(2026, 10, 10, 9, 30, tzinfo=timezone.utc)
    assert occurrence_end == datetime(2026, 10, 10, 17, 0, tzinfo=timezone.utc)


def test_combine_occurrence_window_clamps_an_inverted_legacy_template():
    """A one-day occurrence (start_d == end_d) whose template's end time
    precedes its start time — e.g. a row persisted before create/update
    validation guarded against it — must never surface end < start to a
    reader (event lists, featured events, group feeds)."""
    start_d = end_d = date(2026, 10, 10)
    template_start = datetime(2020, 1, 1, 17, 0, tzinfo=timezone.utc)
    template_end = datetime(2020, 1, 1, 9, 30, tzinfo=timezone.utc)

    occurrence_start, occurrence_end = combine_occurrence_window(
        start_d, end_d, template_start, template_end
    )

    assert occurrence_start == datetime(2026, 10, 10, 17, 0, tzinfo=timezone.utc)
    assert occurrence_end == occurrence_start
    assert occurrence_end >= occurrence_start
