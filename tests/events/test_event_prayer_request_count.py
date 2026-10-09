from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.events.event_service import _prayer_request_count_for_event


@patch("pecha_api.chat.repository.count_prayer_requests_in_room", return_value=7)
@patch("pecha_api.chat.repository.get_room_by_event_id")
def test_prayer_request_count_for_event_with_room(mock_get_room, mock_count):
    db = MagicMock()
    event_id = uuid4()
    room = MagicMock(id=uuid4())
    mock_get_room.return_value = room

    count = _prayer_request_count_for_event(db=db, event_id=event_id)

    assert count == 7
    mock_get_room.assert_called_once_with(db=db, event_id=event_id)
    mock_count.assert_called_once_with(db=db, room_id=room.id)


@patch("pecha_api.chat.repository.count_prayer_requests_in_room")
@patch("pecha_api.chat.repository.get_room_by_event_id", return_value=None)
def test_prayer_request_count_for_event_without_room(mock_get_room, mock_count):
    db = MagicMock()
    event_id = uuid4()

    count = _prayer_request_count_for_event(db=db, event_id=event_id)

    assert count == 0
    mock_count.assert_not_called()
