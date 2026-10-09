from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.feedback.feedback_response_models import FeedbackDTO

client = TestClient(api)

SERVICE = "pecha_api.feedback.feedback_views.submit_feedback_service"


def _dto(**overrides) -> FeedbackDTO:
    now = datetime.now(timezone.utc)
    values = dict(
        id=uuid4(),
        user_id=uuid4(),
        content="Great app",
        image_urls=[],
        platform="android 14",
        app_version="2.3.1",
        created_at=now,
        updated_at=now,
    )
    values.update(overrides)
    return FeedbackDTO(**values)


def test_submit_feedback_with_images():
    dto = _dto(image_urls=["https://signed/1", "https://signed/2"])

    with patch(SERVICE, return_value=dto) as mock_service:
        response = client.post(
            "/feedback",
            data={"content": "Great app", "platform": "android 14", "app_version": "2.3.1"},
            files=[
                ("images", ("a.jpg", b"one", "image/jpeg")),
                ("images", ("b.jpg", b"two", "image/jpeg")),
            ],
            headers={"Authorization": "Bearer test_token"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["id"] == str(dto.id)
    assert body["image_urls"] == ["https://signed/1", "https://signed/2"]

    kwargs = mock_service.call_args.kwargs
    assert kwargs["token"] == "test_token"
    assert kwargs["content"] == "Great app"
    assert kwargs["platform"] == "android 14"
    assert kwargs["app_version"] == "2.3.1"
    assert [image.filename for image in kwargs["images"]] == ["a.jpg", "b.jpg"]


def test_submit_feedback_content_only():
    with patch(SERVICE, return_value=_dto(platform=None, app_version=None)) as mock_service:
        response = client.post(
            "/feedback",
            data={"content": "Great app"},
            headers={"Authorization": "Bearer test_token"},
        )

    assert response.status_code == 201
    kwargs = mock_service.call_args.kwargs
    assert kwargs["images"] is None
    assert kwargs["platform"] is None
    assert kwargs["app_version"] is None


def test_submit_feedback_requires_content():
    with patch(SERVICE) as mock_service:
        response = client.post(
            "/feedback",
            data={"platform": "ios"},
            headers={"Authorization": "Bearer test_token"},
        )

    assert response.status_code == 422
    mock_service.assert_not_called()


def test_submit_feedback_requires_authentication():
    with patch(SERVICE) as mock_service:
        response = client.post("/feedback", data={"content": "Great app"})

    assert response.status_code in (401, 403)
    mock_service.assert_not_called()
