from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.prayer_intentions.prayer_intention_response_models import (
    PrayerIntentionDTO,
    PrayerIntentionsResponse,
)

client = TestClient(api)


class TestPublicIntentionsEndpoint:
    @patch(
        "pecha_api.prayer_intentions.prayer_intention_views.get_all_prayer_intentions_service"
    )
    def test_get_intentions_without_event(self, mock_service):
        mock_service.return_value = PrayerIntentionsResponse(
            intentions=[
                PrayerIntentionDTO(
                    slug="healing",
                    label="Healing",
                    color="#4A78C2",
                    description="Recovery",
                    display_order=0,
                )
            ]
        )

        response = client.get("/intentions")

        assert response.status_code == 200
        assert response.json()["intentions"][0]["slug"] == "healing"
        mock_service.assert_called_once_with(None)

    @patch(
        "pecha_api.prayer_intentions.prayer_intention_views.get_all_prayer_intentions_service"
    )
    def test_get_intentions_with_event_query(self, mock_service):
        event_id = uuid4()
        mock_service.return_value = PrayerIntentionsResponse(intentions=[])

        response = client.get("/intentions", params={"event": str(event_id)})

        assert response.status_code == 200
        mock_service.assert_called_once_with(event_id)
