from datetime import datetime, timezone
from uuid import uuid4

from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch

from pecha_api.app import api
from pecha_api.events.event_response_models import EventDTO, EventsResponse

client = TestClient(api)


NULLABLE_EVENT_FIELDS = (
    "plan_id",
    "accumulator_id",
    "mantra_id",
    "timer_id",
    "image",
    "image_url",
    "updated_at",
    "is_joined",
    "recurrence",
    "occurrence_date",
    "start_time",
    "end_time",
)


def _minimal_events_payload() -> EventsResponse:
    now = datetime.now(timezone.utc)
    event = EventDTO(
        id=uuid4(),
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        is_one_day=True,
        featured=False,
        metadata=[],
        created_at=now,
        created_by="author@example.com",
    )
    return EventsResponse(events=[event], total=1, skip=0, limit=20)


def test_events_today_response_includes_null_fields():
    with patch(
        "pecha_api.events.event_views.get_events_today_service_cached",
        new_callable=AsyncMock,
        return_value=_minimal_events_payload(),
    ):
        response = client.get("/events/today")

    event_body = response.json()["events"][0]
    for field in NULLABLE_EVENT_FIELDS:
        assert field in event_body
        assert event_body[field] is None
    assert event_body["event_format"] == "hybrid"


def test_events_list_response_omits_null_fields():
    with patch(
        "pecha_api.events.event_views.get_events_service_cached",
        new_callable=AsyncMock,
        return_value=_minimal_events_payload(),
    ):
        response = client.get("/events")

    event_body = response.json()["events"][0]
    for field in NULLABLE_EVENT_FIELDS:
        assert field not in event_body
    assert event_body["event_format"] == "hybrid"


def test_event_response_includes_event_format_when_set():
    now = datetime.now(timezone.utc)
    event = EventDTO(
        id=uuid4(),
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        is_one_day=True,
        featured=False,
        event_format="online",
        metadata=[],
        created_at=now,
        created_by="author@example.com",
    )
    payload = EventsResponse(events=[event], total=1, skip=0, limit=20)

    with patch(
        "pecha_api.events.event_views.get_events_today_service_cached",
        new_callable=AsyncMock,
        return_value=payload,
    ):
        response = client.get("/events/today")

    event_body = response.json()["events"][0]
    assert event_body["event_format"] == "online"
