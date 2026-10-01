from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.prayer_intentions.prayer_intention_response_models import (
    PrayerIntentionCMSDTO,
    PrayerIntentionsCMSListResponse,
)

client = TestClient(api)

_AUTH = {"Authorization": "Bearer dummy"}


def _dto() -> PrayerIntentionCMSDTO:
    return PrayerIntentionCMSDTO(
        id=uuid4(),
        slug="healing",
        label="Healing",
        color="#4A78C2",
        description="Recovery",
        display_order=1,
        linked_event_count=0,
    )


def test_cms_list_requires_auth():
    response = client.get("/cms/intentions")
    assert response.status_code == 403


def test_cms_list_returns_catalog():
    expected = PrayerIntentionsCMSListResponse(intentions=[_dto()])
    with patch(
        "pecha_api.prayer_intentions.cms_views.cms_list_prayer_intentions_service",
        return_value=expected,
    ) as mock_list:
        response = client.get("/cms/intentions", headers=_AUTH)

    assert response.status_code == 200
    assert response.json()["intentions"][0]["slug"] == "healing"
    mock_list.assert_called_once_with(token="dummy")


def test_cms_create_returns_201():
    expected = _dto()
    payload = {
        "slug": "Healing",
        "label": "Healing",
        "color": "#4A78C2",
        "description": "Recovery",
        "display_order": 1,
    }
    with patch(
        "pecha_api.prayer_intentions.cms_views.cms_create_prayer_intention_service",
        return_value=expected,
    ) as mock_create:
        response = client.post("/cms/intentions", json=payload, headers=_AUTH)

    assert response.status_code == 201
    assert response.json()["id"] == str(expected.id)
    mock_create.assert_called_once()


def test_cms_patch_returns_updated_intention():
    intention_id = uuid4()
    expected = _dto()
    with patch(
        "pecha_api.prayer_intentions.cms_views.cms_patch_prayer_intention_service",
        return_value=expected,
    ) as mock_patch:
        response = client.patch(
            f"/cms/intentions/{intention_id}",
            json={"label": "Recovery"},
            headers=_AUTH,
        )

    assert response.status_code == 200
    assert mock_patch.call_args.kwargs["intention_id"] == intention_id
    assert mock_patch.call_args.kwargs["request"].label == "Recovery"


def test_cms_patch_requires_auth():
    response = client.patch(
        f"/cms/intentions/{uuid4()}",
        json={"label": "Recovery"},
    )
    assert response.status_code == 403
