from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.events.event_response_models import EventDTO, EventsResponse

client = TestClient(api)

AUTH = {"Authorization": "Bearer test-token"}


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


# --------------------------- list route ---------------------------


def test_cms_list_requires_auth():
    response = client.get("/cms/events")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_cms_list_success_passes_token_and_filters():
    group_id = uuid4()
    payload = EventsResponse(events=[_sample_event_dto()], total=1, skip=0, limit=20)

    with patch(
        "pecha_api.events.cms_event_views.get_cms_events_service",
        return_value=payload,
    ) as mock_service:
        response = client.get(
            "/cms/events",
            params={"group_id": str(group_id), "language": "en"},
            headers=AUTH,
        )

    assert response.status_code == status.HTTP_200_OK
    assert response.json()["total"] == 1
    kwargs = mock_service.call_args.kwargs
    assert kwargs["token"] == "test-token"
    assert kwargs["group_id"] == group_id
    assert kwargs["language"] == "en"


def test_cms_list_rejects_out_of_range_limit():
    response = client.get("/cms/events", params={"limit": 500}, headers=AUTH)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# --------------------------- detail route ---------------------------


def test_cms_detail_requires_auth():
    response = client.get(f"/cms/events/{uuid4()}")
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_cms_detail_success_passes_token():
    event = _sample_event_dto()

    with patch(
        "pecha_api.events.cms_event_views.get_cms_event_by_id_service",
        return_value=event,
    ) as mock_service:
        response = client.get(f"/cms/events/{event.id}", headers=AUTH)

    assert response.status_code == status.HTTP_200_OK
    kwargs = mock_service.call_args.kwargs
    assert kwargs["token"] == "test-token"
    assert kwargs["event_id"] == event.id
    assert kwargs["language"] is None


def test_cms_detail_invalid_uuid_returns_422():
    response = client.get("/cms/events/not-a-uuid", headers=AUTH)
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_deleting_an_event_stops_its_autoplay_first():
    event_id = uuid4()
    order = []
    engine = AsyncMock()

    async def stop(stopped_event_id, reason="stopped"):
        order.append(("stop", stopped_event_id, reason))

    def delete(token, event_id):
        order.append(("delete", event_id))

    engine.stop.side_effect = stop
    with patch(
        "pecha_api.events.recitation_autoplay_service.get_autoplay_engine",
        return_value=engine,
    ), patch(
        "pecha_api.events.cms_event_views.delete_event_service",
        side_effect=delete,
    ):
        response = client.delete(f"/cms/events/{event_id}", headers=AUTH)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert order == [("stop", event_id, "ended"), ("delete", event_id)]


def test_deleting_an_event_still_deletes_when_autoplay_cannot_be_stopped():
    event_id = uuid4()
    engine = AsyncMock()
    engine.stop.side_effect = RuntimeError("redis down")
    with patch(
        "pecha_api.events.recitation_autoplay_service.get_autoplay_engine",
        return_value=engine,
    ), patch(
        "pecha_api.events.cms_event_views.delete_event_service",
    ) as delete:
        response = client.delete(f"/cms/events/{event_id}", headers=AUTH)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    delete.assert_called_once()
