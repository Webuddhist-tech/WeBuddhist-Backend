from unittest.mock import MagicMock, patch
from uuid import uuid4

import pecha_api.app  # noqa: F401

from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.message_service import _schedule_event_prayer_count_cache_refresh


@patch("pecha_api.chat.message_service.schedule_invalidate_event_detail_caches")
def test_schedule_event_prayer_cache_refresh_for_event_prayer(mock_schedule):
    event_id = uuid4()
    room = MagicMock(event_id=event_id)

    _schedule_event_prayer_count_cache_refresh(
        room=room, message_type=ChatMessageType.PRAYER.value
    )

    mock_schedule.assert_called_once_with(event_id)


@patch("pecha_api.chat.message_service.schedule_invalidate_event_detail_caches")
def test_schedule_event_prayer_cache_refresh_skips_text(mock_schedule):
    room = MagicMock(event_id=uuid4())

    _schedule_event_prayer_count_cache_refresh(
        room=room, message_type=ChatMessageType.TEXT.value
    )

    mock_schedule.assert_not_called()


@patch("pecha_api.chat.message_service.schedule_invalidate_event_detail_caches")
def test_schedule_event_prayer_cache_refresh_skips_group_prayer_without_event(
    mock_schedule,
):
    room = MagicMock(event_id=None)

    _schedule_event_prayer_count_cache_refresh(
        room=room, message_type=ChatMessageType.PRAYER.value
    )

    mock_schedule.assert_not_called()
