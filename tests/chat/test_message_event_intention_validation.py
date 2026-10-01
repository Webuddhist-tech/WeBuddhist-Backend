"""Event chat rooms pass event_id into prayer intention validation."""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.message_service import send_event_message_service
from pecha_api.users.users_models import Users


@pytest.fixture
def mock_user():
    user = MagicMock(spec=Users)
    user.id = uuid4()
    return user


class TestEventMessageIntentionValidation:
    @patch("pecha_api.chat.message_service.enqueue_chat_message_notification")
    @patch("pecha_api.chat.message_service.create_message")
    @patch("pecha_api.chat.message_service.touch_room")
    @patch("pecha_api.chat.message_service._lock_room_publication")
    @patch("pecha_api.chat.message_service.validate_message_content")
    @patch("pecha_api.chat.message_service.validate_message_intention_and_body")
    @patch("pecha_api.chat.message_service._require_active_member")
    @patch("pecha_api.chat.message_service.resolve_or_create_event_room")
    @patch("pecha_api.chat.message_service.SessionLocal")
    @patch("pecha_api.chat.message_service.build_message_dto")
    def test_send_event_prayer_passes_event_id_to_validation(
        self,
        mock_build_dto,
        mock_session,
        mock_resolve_room,
        mock_require_member,
        mock_validate_intention,
        mock_validate_content,
        mock_lock,
        mock_touch,
        mock_create_message,
        mock_enqueue,
        mock_user,
    ):
        event_id = uuid4()
        room = MagicMock()
        room.id = uuid4()
        room.event_id = event_id
        mock_resolve_room.return_value = room
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db

        message = MagicMock()
        message.id = uuid4()
        message.message_type = ChatMessageType.PRAYER.value
        message.sender = mock_user
        mock_create_message.return_value = message
        mock_validate_intention.return_value = "healing"
        mock_build_dto.return_value = MagicMock()

        send_event_message_service(
            event_id=event_id,
            user=mock_user,
            body="Please pray",
            message_type=ChatMessageType.PRAYER.value,
            intention="healing",
        )

        mock_validate_intention.assert_called_once()
        assert mock_validate_intention.call_args.kwargs["event_id"] == event_id
