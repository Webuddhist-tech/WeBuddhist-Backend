from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.events.event_response_models import EventDTO

client = TestClient(api)


def _sample_event_dto(featured=True) -> EventDTO:
    now = datetime.now(timezone.utc)
    return EventDTO(
        id=uuid4(),
        group_id=uuid4(),
        start_date=now,
        end_date=now,
        is_one_day=True,
        featured=featured,
        metadata=[],
        created_at=now,
        created_by="author@example.com",
    )


# --------------------------- GET /events/featured ---------------------------


def test_get_featured_events_success():
    event1 = _sample_event_dto()
    event2 = _sample_event_dto()
    
    with patch(
        "pecha_api.events.event_views.get_featured_events_service_cached",
        new_callable=AsyncMock,
        return_value=[event1, event2],
    ) as mock_service:
        response = client.get("/events/featured")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert len(body) == 2
    assert all(event["featured"] is True for event in body)
    mock_service.assert_called_once_with(language="en", limit=10, token=None)


def test_get_featured_events_default_params():
    with patch(
        "pecha_api.events.event_views.get_featured_events_service_cached",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_service:
        response = client.get("/events/featured")

    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(language="en", limit=10, token=None)


def test_get_featured_events_custom_params():
    event = _sample_event_dto()
    
    with patch(
        "pecha_api.events.event_views.get_featured_events_service_cached",
        new_callable=AsyncMock,
        return_value=[event],
    ) as mock_service:
        response = client.get("/events/featured?language=bo&limit=5")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert len(body) == 1
    mock_service.assert_called_once_with(language="bo", limit=5, token=None)


def test_get_featured_events_empty():
    with patch(
        "pecha_api.events.event_views.get_featured_events_service_cached",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_service:
        response = client.get("/events/featured")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body == []
    mock_service.assert_called_once_with(language="en", limit=10, token=None)


def test_get_featured_events_max_limit():
    events = [_sample_event_dto() for _ in range(20)]
    
    with patch(
        "pecha_api.events.event_views.get_featured_events_service_cached",
        new_callable=AsyncMock,
        return_value=events,
    ) as mock_service:
        response = client.get("/events/featured?limit=100")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert len(body) == 20
    mock_service.assert_called_once_with(language="en", limit=100, token=None)


def test_get_featured_events_forwards_optional_token():
    with patch(
        "pecha_api.events.event_views.get_featured_events_service_cached",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_service:
        response = client.get(
            "/events/featured",
            headers={"Authorization": "Bearer user-token"},
        )

    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(language="en", limit=10, token="user-token")


def test_get_featured_events_invalid_limit():
    response = client.get("/events/featured?limit=0")
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


# --------------------------- PATCH /cms/events/{id}/featured ---------------------------


def test_patch_featured_success():
    event_id = uuid4()
    
    with patch(
        "pecha_api.events.cms_event_views.update_event_featured_service",
        return_value=None,
    ) as mock_service:
        response = client.patch(
            f"/cms/events/{event_id}/featured",
            headers={"Authorization": "Bearer dummy_token"},
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_service.assert_called_once_with(token="dummy_token", event_id=event_id)


def test_patch_featured_unauthorized():
    event_id = uuid4()
    
    response = client.patch(f"/cms/events/{event_id}/featured")
    
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_patch_featured_not_found():
    event_id = uuid4()
    
    with patch(
        "pecha_api.events.cms_event_views.update_event_featured_service",
        side_effect=HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Event with id '{event_id}' not found",
        ),
    ) as mock_service:
        response = client.patch(
            f"/cms/events/{event_id}/featured",
            headers={"Authorization": "Bearer dummy_token"},
        )

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert "not found" in response.json()["detail"]


def test_patch_featured_forbidden():
    event_id = uuid4()
    
    with patch(
        "pecha_api.events.cms_event_views.update_event_featured_service",
        side_effect=HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="STATUS_CHANGE_FORBIDDEN",
        ),
    ) as mock_service:
        response = client.patch(
            f"/cms/events/{event_id}/featured",
            headers={"Authorization": "Bearer dummy_token"},
        )

    assert response.status_code == status.HTTP_403_FORBIDDEN
    assert response.json()["detail"] == "STATUS_CHANGE_FORBIDDEN"


def test_patch_featured_invalid_uuid():
    response = client.patch(
        "/cms/events/invalid-uuid/featured",
        headers={"Authorization": "Bearer dummy_token"},
    )
    
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_patch_featured_multiple_toggles():
    event_id = uuid4()
    
    with patch(
        "pecha_api.events.cms_event_views.update_event_featured_service",
        return_value=None,
    ) as mock_service:
        response1 = client.patch(
            f"/cms/events/{event_id}/featured",
            headers={"Authorization": "Bearer dummy_token"},
        )
        response2 = client.patch(
            f"/cms/events/{event_id}/featured",
            headers={"Authorization": "Bearer dummy_token"},
        )

    assert response1.status_code == status.HTTP_204_NO_CONTENT
    assert response2.status_code == status.HTTP_204_NO_CONTENT
    assert mock_service.call_count == 2
