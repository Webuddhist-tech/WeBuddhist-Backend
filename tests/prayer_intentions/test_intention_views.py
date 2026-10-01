import asyncio
from typing import Any, Callable, TypeVar
from unittest.mock import patch
from uuid import uuid4

from pecha_api.prayer_intentions.prayer_intention_response_models import (
    PrayerIntentionDTO,
    PrayerIntentionsResponse,
)
from pecha_api.prayer_intentions.prayer_intention_views import get_prayer_intentions

T = TypeVar("T")


async def fake_run_in_threadpool(
    fn: Callable[..., T], *args: Any, **kwargs: Any
) -> T:
    return fn(*args, **kwargs)


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
            side_effect=fake_run_in_threadpool,
        ):
            result = asyncio.run(get_prayer_intentions())

        assert result == expected
        mock_service.assert_called_once_with(None)

    @patch("pecha_api.prayer_intentions.prayer_intention_views.get_all_prayer_intentions_service")
    def test_forwards_event_filter(self, mock_service):
        event_id = uuid4()
        expected = PrayerIntentionsResponse(intentions=[])
        mock_service.return_value = expected

        with patch(
            "pecha_api.prayer_intentions.prayer_intention_views.run_in_threadpool",
            side_effect=fake_run_in_threadpool,
        ):
            result = asyncio.run(get_prayer_intentions(event=event_id))

        assert result == expected
        mock_service.assert_called_once_with(event_id)
