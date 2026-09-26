from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.events.event_response_models import EventDTO, EventsResponse

client = TestClient(api)


def _sample_event_dto() -> EventDTO:
    now = datetime.now(timezone.utc)
    return EventDTO(
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


def test_get_events_forwards_include_unfollowed():
    response_payload = EventsResponse(events=[], total=0, skip=0, limit=20)

    with patch(
        "pecha_api.events.event_views.get_events_service_cached",
        new_callable=AsyncMock,
        return_value=response_payload,
    ) as mock_service:
        response = client.get("/events?include_unfollowed=true")

    assert response.status_code == status.HTTP_200_OK
    assert mock_service.call_args.kwargs["should_include_unfollowed"] is True


def test_get_events_today_success():
    event = _sample_event_dto()
    response_payload = EventsResponse(events=[event], total=1, skip=0, limit=20)

    with patch(
        "pecha_api.events.event_views.get_events_today_service_cached",
        new_callable=AsyncMock,
        return_value=response_payload,
    ) as mock_service:
        response = client.get("/events/today")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["total"] == 1
    assert len(body["events"]) == 1
    mock_service.assert_called_once_with(
        timezone=None,
        group_id=None,
        language=None,
        should_include_unfollowed=False,
        skip=0,
        limit=20,
        token=None,
    )


def test_get_events_today_with_timezone_header():
    response_payload = EventsResponse(events=[], total=0, skip=0, limit=20)

    with patch(
        "pecha_api.events.event_views.get_events_today_service_cached",
        new_callable=AsyncMock,
        return_value=response_payload,
    ) as mock_service:
        response = client.get(
            "/events/today",
            headers={"X-Timezone": "America/New_York"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(
        timezone="America/New_York",
        group_id=None,
        language=None,
        should_include_unfollowed=False,
        skip=0,
        limit=20,
        token=None,
    )


def test_get_events_today_forwards_optional_token():
    response_payload = EventsResponse(events=[], total=0, skip=0, limit=20)

    with patch(
        "pecha_api.events.event_views.get_events_today_service_cached",
        new_callable=AsyncMock,
        return_value=response_payload,
    ) as mock_service:
        response = client.get(
            "/events/today",
            headers={"Authorization": "Bearer user-token"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(
        timezone=None,
        group_id=None,
        language=None,
        should_include_unfollowed=False,
        skip=0,
        limit=20,
        token="user-token",
    )


def test_get_events_today_forwards_include_unfollowed():
    response_payload = EventsResponse(events=[], total=0, skip=0, limit=20)

    with patch(
        "pecha_api.events.event_views.get_events_today_service_cached",
        new_callable=AsyncMock,
        return_value=response_payload,
    ) as mock_service:
        response = client.get("/events/today?include_unfollowed=true")

    assert response.status_code == status.HTTP_200_OK
    assert mock_service.call_args.kwargs["should_include_unfollowed"] is True


def test_get_event_by_id_forwards_optional_token():
    event = _sample_event_dto()
    event_id = event.id

    with patch(
        "pecha_api.events.event_views.get_event_by_id_service_cached",
        new_callable=AsyncMock,
        return_value=event,
    ) as mock_service:
        response = client.get(
            f"/events/{event_id}",
            headers={"Authorization": "Bearer user-token"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(
        event_id=event_id,
        language=None,
        token="user-token",
    )


def test_get_events_today_invalid_timezone():
    response = client.get(
        "/events/today",
        headers={"X-Timezone": "Not/A_Timezone"},
    )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
