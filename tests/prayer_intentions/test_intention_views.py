import asyncio
from unittest.mock import patch

from pecha_api.prayer_intentions.prayer_intention_response_models import (
    PrayerIntentionDTO,
    PrayerIntentionsResponse,
)
from pecha_api.prayer_intentions.prayer_intention_views import get_prayer_intentions


class TestGetPrayerIntentions:
    @patch("pecha_api.prayer_intentions.prayer_intention_views.get_all_prayer_intentions_service")
    def test_returns_catalog(self, mock_service):
        expected = PrayerIntentionsResponse(
            intentions=[
                PrayerIntentionDTO(
                    slug="healing",
                    label="Healing",
                    color="#4A78C2",
                    description="For illness, surgery and recovery.",
                    display_order=0,
                )
            ]
        )
        mock_service.return_value = expected

        with patch(
            "pecha_api.prayer_intentions.prayer_intention_views.run_in_threadpool",
            side_effect=lambda fn: fn(),
        ):
            result = asyncio.run(get_prayer_intentions())

        assert result == expected
        mock_service.assert_called_once_with()
