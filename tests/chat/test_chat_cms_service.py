import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone as tz
from fastapi import HTTPException
from starlette import status

# Import the app first so the full SQLAlchemy model registry is configured.
import pecha_api.app  # noqa: F401

from pecha_api.chat.cms_service import cms_delete_group_chat_message_service


class MockAuthor:
    def __init__(self, first_name="Tenzin", last_name="Kunsang", email="mod@example.com"):
        self.id = uuid4()
        self.first_name = first_name
        self.last_name = last_name
        self.email = email


class MockMessage:
    def __init__(self, sender_id=None, room_id=None):
        self.id = uuid4()
        self.room_id = room_id or uuid4()
        self.sender_id = sender_id or uuid4()
        self.body = "Hello"
        self.created_at = datetime.now(tz.utc)
        self.deleted_at = None


def _room():
    room = MagicMock()
    room.id = uuid4()
    return room


class TestCmsDeleteGroupChatMessageService:

    @patch('pecha_api.chat.cms_service.soft_delete_message')
    @patch('pecha_api.chat.cms_service.get_message_by_id')
    @patch('pecha_api.chat.cms_service.require_can_create_content')
    @patch('pecha_api.chat.cms_service.get_room_by_group_id')
    @patch('pecha_api.chat.cms_service.get_group_by_id')
    @patch('pecha_api.chat.cms_service.validate_and_extract_author_details')
    @patch('pecha_api.chat.cms_service.SessionLocal')
    def test_deletes_another_users_message(
        self, mock_session, mock_author, mock_get_group, mock_get_room,
        mock_require, mock_get_message, mock_soft_delete,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        author = MockAuthor()
        mock_author.return_value = author
        mock_get_group.return_value = MagicMock()
        room = _room()
        mock_get_room.return_value = room
        message = MockMessage(room_id=room.id)  # sent by somebody else entirely
        mock_get_message.return_value = message
        deleted_at = datetime.now(tz.utc)
        mock_soft_delete.return_value = deleted_at

        group_id = uuid4()
        result = cms_delete_group_chat_message_service(
            token="t", group_id=group_id, message_id=message.id
        )

        mock_require.assert_called_once()
        assert mock_require.call_args.kwargs["group_id"] == group_id
        assert mock_require.call_args.kwargs["author"] is author
        mock_soft_delete.assert_called_once()
        assert mock_soft_delete.call_args.kwargs["message"] is message
        assert result.room_id == room.id
        assert result.deleted_at == deleted_at.isoformat()
        assert result.deleted_by == {
            "user_id": str(author.id),
            "email": author.email,
            "name": "Tenzin Kunsang",
            "source": "CMS",
        }

    @patch('pecha_api.chat.cms_service.soft_delete_message')
    @patch('pecha_api.chat.cms_service.get_message_by_id')
    @patch('pecha_api.chat.cms_service.require_can_create_content')
    @patch('pecha_api.chat.cms_service.get_room_by_group_id')
    @patch('pecha_api.chat.cms_service.get_group_by_id')
    @patch('pecha_api.chat.cms_service.validate_and_extract_author_details')
    @patch('pecha_api.chat.cms_service.SessionLocal')
    def test_forbidden_without_content_permission(
        self, mock_session, mock_author, mock_get_group, mock_get_room,
        mock_require, mock_get_message, mock_soft_delete,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_get_group.return_value = MagicMock()
        mock_get_room.return_value = _room()
        mock_require.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="NO_GROUP_MEMBERSHIP"
        )

        with pytest.raises(HTTPException) as exc_info:
            cms_delete_group_chat_message_service(
                token="t", group_id=uuid4(), message_id=uuid4()
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        # Nothing is read or deleted once the role check fails.
        mock_get_room.assert_not_called()
        mock_get_message.assert_not_called()
        mock_soft_delete.assert_not_called()

    @patch('pecha_api.chat.cms_service.soft_delete_message')
    @patch('pecha_api.chat.cms_service.get_message_by_id')
    @patch('pecha_api.chat.cms_service.require_can_create_content')
    @patch('pecha_api.chat.cms_service.get_room_by_group_id')
    @patch('pecha_api.chat.cms_service.get_group_by_id')
    @patch('pecha_api.chat.cms_service.validate_and_extract_author_details')
    @patch('pecha_api.chat.cms_service.SessionLocal')
    def test_message_not_in_this_room_is_404(
        self, mock_session, mock_author, mock_get_group, mock_get_room,
        mock_require, mock_get_message, mock_soft_delete,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_get_group.return_value = MagicMock()
        room = _room()
        mock_get_room.return_value = room
        mock_get_message.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            cms_delete_group_chat_message_service(
                token="t", group_id=uuid4(), message_id=uuid4()
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert mock_get_message.call_args.kwargs["room_id"] == room.id
        mock_soft_delete.assert_not_called()

    @patch('pecha_api.chat.cms_service.require_can_create_content')
    @patch('pecha_api.chat.cms_service.get_room_by_group_id')
    @patch('pecha_api.chat.cms_service.get_group_by_id')
    @patch('pecha_api.chat.cms_service.validate_and_extract_author_details')
    @patch('pecha_api.chat.cms_service.SessionLocal')
    def test_unknown_group_is_404(
        self, mock_session, mock_author, mock_get_group, mock_get_room, mock_require
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_get_group.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            cms_delete_group_chat_message_service(
                token="t", group_id=uuid4(), message_id=uuid4()
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        mock_get_room.assert_not_called()
        mock_require.assert_not_called()

    @patch('pecha_api.chat.cms_service.require_can_create_content')
    @patch('pecha_api.chat.cms_service.get_room_by_group_id')
    @patch('pecha_api.chat.cms_service.get_group_by_id')
    @patch('pecha_api.chat.cms_service.validate_and_extract_author_details')
    @patch('pecha_api.chat.cms_service.SessionLocal')
    def test_group_without_a_chat_room_is_404(
        self, mock_session, mock_author, mock_get_group, mock_get_room, mock_require
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_get_group.return_value = MagicMock()
        mock_get_room.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            cms_delete_group_chat_message_service(
                token="t", group_id=uuid4(), message_id=uuid4()
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        # The role check runs before the room lookup, so a caller with no role
        # in the group cannot probe whether its chat room exists.
        mock_require.assert_called_once()

    @patch('pecha_api.chat.cms_service.soft_delete_message')
    @patch('pecha_api.chat.cms_service.get_message_by_id')
    @patch('pecha_api.chat.cms_service.require_can_create_content')
    @patch('pecha_api.chat.cms_service.get_room_by_group_id')
    @patch('pecha_api.chat.cms_service.get_group_by_id')
    @patch('pecha_api.chat.cms_service.validate_and_extract_author_details')
    @patch('pecha_api.chat.cms_service.SessionLocal')
    def test_actor_name_falls_back_to_email(
        self, mock_session, mock_author, mock_get_group, mock_get_room,
        mock_require, mock_get_message, mock_soft_delete,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor(first_name="", last_name=None)
        mock_get_group.return_value = MagicMock()
        mock_get_room.return_value = _room()
        mock_get_message.return_value = MockMessage()
        mock_soft_delete.return_value = datetime.now(tz.utc)

        result = cms_delete_group_chat_message_service(
            token="t", group_id=uuid4(), message_id=uuid4()
        )

        assert result.deleted_by["name"] == "mod@example.com"
