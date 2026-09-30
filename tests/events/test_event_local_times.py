"""start_time / end_time on EventDTO: the event's wall-clock HH:MM in its own
timezone, so clients don't have to convert the UTC start_date/end_date."""
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch
from uuid import uuid4

from pecha_api.events.event_service import _event_to_dto, _local_hhmm

MODULE = "pecha_api.events.event_service"


def _event(**overrides: Any) -> SimpleNamespace:
    start = datetime(2026, 9, 25, 2, 30, tzinfo=timezone.utc)
    end = datetime(2026, 10, 15, 11, 30, tzinfo=timezone.utc)
    base = dict(
        id=uuid4(),
        plan_id=None,
        plan=None,
        accumulator_id=None,
        accumulator=None,
        mantra_id=None,
        mantra=None,
        timer_id=None,
        timer=None,
        group_recitation_collection_id=None,
        group_recitation_collection=None,
        group_id=uuid4(),
        location_id=None,
        location=None,
        start_date=start,
        end_date=end,
        timezone="Asia/Kolkata",
        image_url=None,
        featured=False,
        event_format="hybrid",
        is_recurring=False,
        metadata_entries=[],
        links=[],
        created_at=start,
        created_by="author@example.com",
        updated_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_local_hhmm_converts_to_event_timezone() -> None:
    value = datetime(2026, 9, 25, 2, 30, tzinfo=timezone.utc)

    assert _local_hhmm(value, "Asia/Kolkata") == "08:00"
    assert _local_hhmm(value, "America/New_York") == "22:30"


def test_local_hhmm_treats_naive_datetime_as_utc() -> None:
    assert _local_hhmm(datetime(2026, 9, 25, 2, 30), "Asia/Kolkata") == "08:00"


@patch(f"{MODULE}.get", return_value="Asia/Kolkata")
def test_local_hhmm_uses_default_zone_when_event_has_none(_mock_get) -> None:
    value = datetime(2026, 9, 25, 2, 30, tzinfo=timezone.utc)

    assert _local_hhmm(value, None) == "08:00"


def test_local_hhmm_falls_back_to_utc_for_unknown_zone() -> None:
    value = datetime(2026, 9, 25, 2, 30, tzinfo=timezone.utc)

    assert _local_hhmm(value, "Not/AZone") == "02:30"


def test_event_to_dto_sets_local_start_and_end_time() -> None:
    dto = _event_to_dto(_event())

    assert dto.start_time == "08:00"
    assert dto.end_time == "17:00"


def test_event_to_dto_times_follow_occurrence_dates() -> None:
    occurrence_start = datetime(2026, 11, 1, 4, 0, tzinfo=timezone.utc)
    occurrence_end = datetime(2026, 11, 1, 6, 15, tzinfo=timezone.utc)

    dto = _event_to_dto(
        _event(),
        start_date=occurrence_start,
        end_date=occurrence_end,
        occurrence_date=occurrence_start,
    )

    assert dto.start_time == "09:30"
    assert dto.end_time == "11:45"
