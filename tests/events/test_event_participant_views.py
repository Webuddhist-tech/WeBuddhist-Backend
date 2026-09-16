from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from starlette import status

from pecha_api.app import api
from pecha_api.events.event_response_models import (
    EventParticipantDTO,
    EventParticipantsResponse,
)

client = TestClient(api)

_AUTH = {"Authorization": "Bearer test-token"}


def _sample_participants_response(total: int = 1) -> EventParticipantsResponse:
    now = datetime.now(timezone.utc)
    return EventParticipantsResponse(
        participants=[
            EventParticipantDTO(
                user_id=uuid4(),
                username="lena",
                fullname="Lena T.",
                avatar_url="https://example.com/a.png",
                created_at=now,
            )
        ],
        skip=0,
        limit=20,
        total=total,
    )


# --- POST /events/{id}/participants (join) ---

def test_join_event_returns_204():
    event_id = uuid4()
    with patch(
        "pecha_api.events.event_views.join_event_service",
        return_value=None,
    ) as mock_service:
        response = client.post(f"/events/{event_id}/participants", headers=_AUTH)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert response.content == b""
    mock_service.assert_called_once_with(
        token="test-token", event_id=event_id, participation_type=None
    )


def test_join_event_requires_token():
    response = client.post(f"/events/{uuid4()}/participants")
    assert response.status_code == status.HTTP_403_FORBIDDEN


# --- DELETE /events/{id}/participants/me (leave) ---

def test_leave_event_returns_204():
    event_id = uuid4()
    with patch(
        "pecha_api.events.event_views.leave_event_service",
        return_value=None,
    ) as mock_service:
        response = client.delete(
            f"/events/{event_id}/participants/me", headers=_AUTH
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    mock_service.assert_called_once_with(token="test-token", event_id=event_id)


def test_leave_event_requires_token():
    response = client.delete(f"/events/{uuid4()}/participants/me")
    assert response.status_code == status.HTTP_403_FORBIDDEN


# --- GET /events/{id}/participants (public list) ---

def test_public_list_needs_no_auth():
    event_id = uuid4()
    payload = _sample_participants_response(total=3)
    with patch(
        "pecha_api.events.event_views.get_event_participants_service",
        return_value=payload,
    ) as mock_service:
        response = client.get(f"/events/{event_id}/participants")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["total"] == 3
    assert len(body["participants"]) == 1
    assert body["participants"][0]["username"] == "lena"
    mock_service.assert_called_once_with(event_id=event_id, skip=0, limit=20)


def test_public_list_passes_pagination():
    event_id = uuid4()
    with patch(
        "pecha_api.events.event_views.get_event_participants_service",
        return_value=_sample_participants_response(),
    ) as mock_service:
        response = client.get(
            f"/events/{event_id}/participants", params={"skip": 5, "limit": 10}
        )

    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once_with(event_id=event_id, skip=5, limit=10)


def test_public_list_rejects_bad_limit():
    response = client.get(
        f"/events/{uuid4()}/participants", params={"limit": 500}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_participants_route_not_shadowed_by_event_id():
    # /{event_id}/participants must not be swallowed by /{event_id}
    event_id = uuid4()
    with patch(
        "pecha_api.events.event_views.get_event_participants_service",
        return_value=_sample_participants_response(),
    ) as mock_service:
        response = client.get(f"/events/{event_id}/participants")

    assert response.status_code == status.HTTP_200_OK
    mock_service.assert_called_once()


# --- GET /cms/events/{id}/participants (CMS list) ---

def test_cms_list_returns_participants():
    event_id = uuid4()
    payload = _sample_participants_response(total=2)
    with patch(
        "pecha_api.events.cms_event_views.get_cms_event_participants_service",
        return_value=payload,
    ) as mock_service:
        response = client.get(
            f"/cms/events/{event_id}/participants", headers=_AUTH
        )

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["total"] == 2
    mock_service.assert_called_once_with(
        token="test-token", event_id=event_id, skip=0, limit=20
    )


def test_cms_list_requires_token():
    response = client.get(f"/cms/events/{uuid4()}/participants")
    assert response.status_code == status.HTTP_403_FORBIDDEN


# --- participation type on join / PATCH ---

def test_join_event_forwards_participation_type():
    event_id = uuid4()
    with patch(
        "pecha_api.events.event_views.join_event_service",
        return_value=None,
    ) as mock_service:
        response = client.post(
            f"/events/{event_id}/participants",
            headers=_AUTH,
            json={"participation_type": "offline"},
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert mock_service.call_args.kwargs["participation_type"] == "offline"


def test_join_event_without_body_sends_no_participation_type():
    event_id = uuid4()
    with patch(
        "pecha_api.events.event_views.join_event_service",
        return_value=None,
    ) as mock_service:
        response = client.post(f"/events/{event_id}/participants", headers=_AUTH)

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert mock_service.call_args.kwargs["participation_type"] is None


def test_update_participation_type_returns_204():
    event_id = uuid4()
    with patch(
        "pecha_api.events.event_views.update_participation_type_service",
        return_value=None,
    ) as mock_service:
        response = client.patch(
            f"/events/{event_id}/participants/me",
            headers=_AUTH,
            json={"participation_type": "online"},
        )

    assert response.status_code == status.HTTP_204_NO_CONTENT
    assert response.content == b""
    kwargs = mock_service.call_args.kwargs
    assert kwargs["token"] == "test-token"
    assert kwargs["event_id"] == event_id
    assert kwargs["participation_type"] == "online"


def test_update_participation_type_requires_token():
    response = client.patch(
        f"/events/{uuid4()}/participants/me",
        json={"participation_type": "online"},
    )
    assert response.status_code == status.HTTP_403_FORBIDDEN


def test_update_participation_type_rejects_unknown_value():
    with patch(
        "pecha_api.events.event_views.update_participation_type_service",
        return_value=None,
    ) as mock_service:
        response = client.patch(
            f"/events/{uuid4()}/participants/me",
            headers=_AUTH,
            json={"participation_type": "hybrid"},
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    mock_service.assert_not_called()


def test_update_participation_type_requires_body():
    with patch(
        "pecha_api.events.event_views.update_participation_type_service",
        return_value=None,
    ) as mock_service:
        response = client.patch(
            f"/events/{uuid4()}/participants/me", headers=_AUTH
        )

    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    mock_service.assert_not_called()
