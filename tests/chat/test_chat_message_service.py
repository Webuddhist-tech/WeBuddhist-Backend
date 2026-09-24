import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone as tz
from fastapi import HTTPException
from starlette import status

# Import the app first so the full SQLAlchemy model registry is configured
# before any ChatRoom()/ChatRoomMember() instantiation below triggers mapper configuration.
import pecha_api.app  # noqa: F401

from pecha_api.chat.message_service import (
    add_message_reaction_service,
    delete_message_service,
    delete_messages_service,
    list_room_messages_service,
    remove_message_reaction_service,
    report_message_service,
    send_direct_message_service,
    send_group_message_service,
)
from pecha_api.chat.enums import ChatMessageReportReason


class MockUser:
    def __init__(self, user_id=None, email="user@example.com", firstname="Alice", lastname=None, avatar_url=None):
        self.id = user_id or uuid4()
        self.email = email
        self.firstname = firstname
        self.lastname = lastname
        self.avatar_url = avatar_url


class MockMember:
    def __init__(self, room_id=None, user_id=None, role="MEMBER"):
        self.id = uuid4()
        self.room_id = room_id or uuid4()
        self.user_id = user_id or uuid4()
        self.role = role
        self.left_at = None


class MockMessage:
    def __init__(self, sender=None, sender_id=None, room_id=None, body="Hello", parent=None):
        self.id = uuid4()
        self.room_id = room_id or uuid4()
        self.sender_id = sender_id or uuid4()
        self.sender = sender or MockUser(user_id=self.sender_id)
        self.body = body
        self.created_at = datetime.now(tz.utc)
        self.deleted_at = None
        self.parent = parent
        self.parent_message_id = parent.id if parent else None


class MockReaction:
    def __init__(self, message_id=None, user_id=None, emoji="🙏"):
        self.id = uuid4()
        self.message_id = message_id or uuid4()
        self.user_id = user_id or uuid4()
        self.emoji = emoji
        self.created_at = datetime.now(tz.utc)


class TestSendGroupMessageService:

    @patch('pecha_api.chat.message_service.touch_room')
    @patch('pecha_api.chat.message_service.create_message')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service.resolve_or_create_group_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_sends_message_when_member(
        self, mock_session, mock_resolve, mock_require_member,
        mock_create_message, mock_touch,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MagicMock(id=uuid4())
        mock_resolve.return_value = room
        user = MockUser()
        mock_require_member.return_value = MockMember(room_id=room.id, user_id=user.id)
        mock_create_message.return_value = MockMessage(sender=user, sender_id=user.id, room_id=room.id, body="Hi")

        result = send_group_message_service(group_id=uuid4(), user=user, body="Hi")

        assert result.body == "Hi"
        mock_touch.assert_called_once()

    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service.resolve_or_create_group_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_non_member_forbidden_on_existing_room(
        self, mock_session, mock_resolve, mock_require_member
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_resolve.return_value = MagicMock(id=uuid4())
        mock_require_member.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"
        )

        with pytest.raises(HTTPException) as exc_info:
            send_group_message_service(group_id=uuid4(), user=MockUser(), body="Hi")

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


class TestSendDirectMessageService:

    @patch('pecha_api.chat.message_service.touch_room')
    @patch('pecha_api.chat.message_service.create_message')
    @patch('pecha_api.chat.message_service.resolve_or_create_private_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_sends_dm(self, mock_session, mock_resolve, mock_create_message, mock_touch):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MagicMock(id=uuid4())
        mock_resolve.return_value = room
        user = MockUser()
        mock_create_message.return_value = MockMessage(sender=user, sender_id=user.id, room_id=room.id, body="Hey")

        result = send_direct_message_service(receiver_id=uuid4(), user=user, body="Hey")

        assert result.body == "Hey"


class TestSendReplyMessage:

    @patch('pecha_api.chat.message_service.touch_room')
    @patch('pecha_api.chat.message_service.create_message')
    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service.resolve_or_create_group_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_reply_includes_parent(
        self, mock_session, mock_resolve, mock_require_member,
        mock_get_parent, mock_create_message, mock_touch,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MagicMock(id=uuid4())
        mock_resolve.return_value = room
        user = MockUser()
        parent = MockMessage(room_id=room.id, body="Original")
        mock_get_parent.return_value = parent
        reply = MockMessage(sender=user, sender_id=user.id, room_id=room.id, body="Reply", parent=parent)
        mock_create_message.return_value = reply

        result = send_group_message_service(
            group_id=uuid4(), user=user, body="Reply", parent_message_id=parent.id
        )

        assert result.body == "Reply"
        assert result.parent is not None
        assert result.parent.id == parent.id
        assert result.parent.body == "Original"
        mock_get_parent.assert_called_once()

    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service.resolve_or_create_group_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_reply_parent_not_found(
        self, mock_session, mock_resolve, mock_require_member, mock_get_parent
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_resolve.return_value = MagicMock(id=uuid4())
        mock_get_parent.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            send_group_message_service(
                group_id=uuid4(), user=MockUser(), body="Reply", parent_message_id=uuid4()
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestListRoomMessagesService:

    @patch('pecha_api.chat.message_service.get_reactions_map')
    @patch('pecha_api.chat.message_service.get_room_messages')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_lists_messages(self, mock_session, mock_get_room, mock_require, mock_get_messages, mock_reactions_map):
        mock_session.return_value.__enter__.return_value = MagicMock()
        message = MockMessage(body="Hi")
        mock_get_messages.return_value = ([message], 1)
        mock_reactions_map.return_value = {}

        result = list_room_messages_service(room_id=uuid4(), user=MockUser(), skip=0, limit=20)

        assert result.total == 1
        assert result.messages[0].body == "Hi"
        assert result.messages[0].reactions == []

    @patch('pecha_api.chat.message_service.get_reactions_map')
    @patch('pecha_api.chat.message_service.get_room_messages')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_lists_messages_with_reactions(
        self, mock_session, mock_get_room, mock_require, mock_get_messages, mock_reactions_map
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        viewer = MockUser()
        message = MockMessage(body="Hi")
        mock_get_messages.return_value = ([message], 1)
        mock_reactions_map.return_value = {
            message.id: [
                MockReaction(message_id=message.id, user_id=viewer.id, emoji="🙏"),
                MockReaction(message_id=message.id, emoji="🙏"),
                MockReaction(message_id=message.id, emoji="❤️"),
            ]
        }

        result = list_room_messages_service(room_id=uuid4(), user=viewer, skip=0, limit=20)

        reactions = {r.emoji: r for r in result.messages[0].reactions}
        assert reactions["🙏"].count == 2
        assert reactions["🙏"].reacted_by_me is True
        assert reactions["❤️"].count == 1
        assert reactions["❤️"].reacted_by_me is False

    @patch('pecha_api.chat.message_service.get_reactions_map')
    @patch('pecha_api.chat.message_service.get_room_messages')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_lists_reply_with_deleted_parent(
        self, mock_session, mock_get_room, mock_require, mock_get_messages, mock_reactions_map
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        parent_sender = MockUser(email="parent@example.com", firstname="Bob")
        parent = MockMessage(sender=parent_sender, sender_id=parent_sender.id, body="Secret")
        parent.deleted_at = datetime.now(tz.utc)
        reply = MockMessage(body="Reply", parent=parent)
        mock_get_messages.return_value = ([reply], 1)
        mock_reactions_map.return_value = {}

        result = list_room_messages_service(room_id=uuid4(), user=MockUser(), skip=0, limit=20)
        parent_dto = result.messages[0].parent

        assert parent_dto is not None
        assert parent_dto.id == parent.id
        assert parent_dto.body == ""
        assert parent_dto.sender_email == "parent@example.com"
        assert parent_dto.sender_name == "Bob"
        assert parent_dto.deleted_at == parent.deleted_at.isoformat()


class TestDeleteMessageService:

    @patch('pecha_api.chat.message_service.soft_delete_message')
    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_deletes_own_message(
        self, mock_session, mock_get_room, mock_require_member,
        mock_get_message, mock_soft_delete,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        user_id = uuid4()
        message = MockMessage(sender_id=user_id)
        mock_get_message.return_value = message
        deleted_at = datetime.now(tz.utc)
        mock_soft_delete.return_value = deleted_at

        result = delete_message_service(room_id=uuid4(), message_id=message.id, user=MockUser(user_id=user_id))

        mock_soft_delete.assert_called_once()
        assert result == deleted_at.isoformat()

    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_cannot_delete_others_message(
        self, mock_session, mock_get_room, mock_require_member, mock_get_message
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        message = MockMessage(sender_id=uuid4())
        mock_get_message.return_value = message

        with pytest.raises(HTTPException) as exc_info:
            delete_message_service(room_id=uuid4(), message_id=message.id, user=MockUser())

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN

    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_message_not_found(
        self, mock_session, mock_get_room, mock_require_member, mock_get_message
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        mock_get_message.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            delete_message_service(room_id=uuid4(), message_id=uuid4(), user=MockUser())

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteMessagesService:

    @patch('pecha_api.chat.message_service.soft_delete_messages')
    @patch('pecha_api.chat.message_service.get_messages_by_ids')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_deletes_own_messages(
        self, mock_session, mock_get_room, mock_require_member,
        mock_get_messages, mock_soft_delete,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        user_id = uuid4()
        first = MockMessage(sender_id=user_id)
        second = MockMessage(sender_id=user_id)
        mock_get_messages.return_value = [second, first]
        deleted_at = datetime.now(tz.utc)
        mock_soft_delete.return_value = deleted_at

        result = delete_messages_service(
            room_id=uuid4(),
            message_ids=[first.id, second.id],
            user=MockUser(user_id=user_id),
        )

        mock_soft_delete.assert_called_once()
        assert mock_soft_delete.call_args.kwargs["messages"] == [first, second]
        assert result.message_ids == [first.id, second.id]
        assert result.deleted_at == deleted_at.isoformat()

    @patch('pecha_api.chat.message_service.soft_delete_messages')
    @patch('pecha_api.chat.message_service.get_messages_by_ids')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_rejects_batch_containing_other_users_message(
        self, mock_session, mock_get_room, mock_require_member,
        mock_get_messages, mock_soft_delete,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        user_id = uuid4()
        mine = MockMessage(sender_id=user_id)
        theirs = MockMessage(sender_id=uuid4())
        mock_get_messages.return_value = [mine, theirs]

        with pytest.raises(HTTPException) as exc_info:
            delete_messages_service(
                room_id=uuid4(),
                message_ids=[mine.id, theirs.id],
                user=MockUser(user_id=user_id),
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        assert str(theirs.id) in exc_info.value.detail
        assert str(mine.id) not in exc_info.value.detail
        # Nothing is deleted when the selection is not entirely the caller's.
        mock_soft_delete.assert_not_called()

    @patch('pecha_api.chat.message_service.soft_delete_messages')
    @patch('pecha_api.chat.message_service.get_messages_by_ids')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_unknown_message_id_deletes_nothing(
        self, mock_session, mock_get_room, mock_require_member,
        mock_get_messages, mock_soft_delete,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        user_id = uuid4()
        mine = MockMessage(sender_id=user_id)
        unknown_id = uuid4()
        mock_get_messages.return_value = [mine]

        with pytest.raises(HTTPException) as exc_info:
            delete_messages_service(
                room_id=uuid4(),
                message_ids=[mine.id, unknown_id],
                user=MockUser(user_id=user_id),
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
        assert str(unknown_id) in exc_info.value.detail
        mock_soft_delete.assert_not_called()

    @patch('pecha_api.chat.message_service.get_messages_by_ids')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_non_member_cannot_bulk_delete(
        self, mock_session, mock_get_room, mock_require_member, mock_get_messages
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="NOT_A_MEMBER"
        )

        with pytest.raises(HTTPException) as exc_info:
            delete_messages_service(
                room_id=uuid4(), message_ids=[uuid4()], user=MockUser()
            )

        assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN
        mock_get_messages.assert_not_called()


class TestAddMessageReactionService:

    @patch('pecha_api.chat.message_service.list_message_reactions')
    @patch('pecha_api.chat.message_service.add_reaction')
    @patch('pecha_api.chat.message_service.get_reaction')
    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_adds_reaction(
        self, mock_session, mock_get_room, mock_require_member,
        mock_get_message, mock_get_reaction, mock_add_reaction, mock_list_reactions,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        user = MockUser()
        message = MockMessage()
        mock_get_message.return_value = message
        mock_get_reaction.return_value = None
        mock_list_reactions.return_value = [
            MockReaction(message_id=message.id, user_id=user.id, emoji="🙏")
        ]

        result = add_message_reaction_service(
            room_id=uuid4(), message_id=message.id, user=user, emoji="🙏"
        )

        mock_add_reaction.assert_called_once()
        assert len(result) == 1
        assert result[0].emoji == "🙏"
        assert result[0].count == 1
        assert result[0].reacted_by_me is True

    @patch('pecha_api.chat.message_service.list_message_reactions')
    @patch('pecha_api.chat.message_service.add_reaction')
    @patch('pecha_api.chat.message_service.get_reaction')
    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_add_reaction_idempotent(
        self, mock_session, mock_get_room, mock_require_member,
        mock_get_message, mock_get_reaction, mock_add_reaction, mock_list_reactions,
    ):
        """Reacting again with the same emoji doesn't create a duplicate."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        user = MockUser()
        message = MockMessage()
        mock_get_message.return_value = message
        existing = MockReaction(message_id=message.id, user_id=user.id, emoji="🙏")
        mock_get_reaction.return_value = existing
        mock_list_reactions.return_value = [existing]

        result = add_message_reaction_service(
            room_id=uuid4(), message_id=message.id, user=user, emoji="🙏"
        )

        mock_add_reaction.assert_not_called()
        assert result[0].count == 1

    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_react_message_not_found(
        self, mock_session, mock_get_room, mock_require_member, mock_get_message
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        mock_get_message.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            add_message_reaction_service(
                room_id=uuid4(), message_id=uuid4(), user=MockUser(), emoji="🙏"
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


class TestRemoveMessageReactionService:

    @patch('pecha_api.chat.message_service.list_message_reactions')
    @patch('pecha_api.chat.message_service.remove_reaction')
    @patch('pecha_api.chat.message_service.get_reaction')
    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_removes_reaction(
        self, mock_session, mock_get_room, mock_require_member,
        mock_get_message, mock_get_reaction, mock_remove_reaction, mock_list_reactions,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        user = MockUser()
        message = MockMessage()
        mock_get_message.return_value = message
        mock_get_reaction.return_value = MockReaction(
            message_id=message.id, user_id=user.id, emoji="🙏"
        )
        mock_list_reactions.return_value = []

        result = remove_message_reaction_service(
            room_id=uuid4(), message_id=message.id, user=user, emoji="🙏"
        )

        mock_remove_reaction.assert_called_once()
        assert result == []

    @patch('pecha_api.chat.message_service.list_message_reactions')
    @patch('pecha_api.chat.message_service.remove_reaction')
    @patch('pecha_api.chat.message_service.get_reaction')
    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_remove_missing_reaction_is_noop(
        self, mock_session, mock_get_room, mock_require_member,
        mock_get_message, mock_get_reaction, mock_remove_reaction, mock_list_reactions,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        message = MockMessage()
        mock_get_message.return_value = message
        mock_get_reaction.return_value = None
        mock_list_reactions.return_value = []

        result = remove_message_reaction_service(
            room_id=uuid4(), message_id=message.id, user=MockUser(), emoji="🙏"
        )

        mock_remove_reaction.assert_not_called()
        assert result == []


class TestReportMessageService:

    @patch('pecha_api.chat.message_service.create_report')
    @patch('pecha_api.chat.message_service.get_report_by_message_and_reporter')
    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_reports_message(
        self, mock_session, mock_get_room, mock_require_member,
        mock_get_message, mock_get_report, mock_create_report,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        message = MockMessage(sender_id=uuid4())
        mock_get_message.return_value = message
        mock_get_report.return_value = None

        report_message_service(
            room_id=uuid4(),
            message_id=message.id,
            user=MockUser(),
            reason=ChatMessageReportReason.SPAM,
            description="Repeated ads",
        )

        mock_create_report.assert_called_once()
        report = mock_create_report.call_args.kwargs['report']
        assert report.reason == "SPAM"
        assert report.description == "Repeated ads"

    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_cannot_report_own_message(
        self, mock_session, mock_get_room, mock_require_member, mock_get_message
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        user = MockUser()
        message = MockMessage(sender=user, sender_id=user.id)
        mock_get_message.return_value = message

        with pytest.raises(HTTPException) as exc_info:
            report_message_service(
                room_id=uuid4(),
                message_id=message.id,
                user=user,
                reason=ChatMessageReportReason.SPAM,
            )

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST

    @patch('pecha_api.chat.message_service.get_report_by_message_and_reporter')
    @patch('pecha_api.chat.message_service.get_message_by_id')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service._get_room_or_404')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_duplicate_report_conflict(
        self, mock_session, mock_get_room, mock_require_member,
        mock_get_message, mock_get_report,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_room.return_value = MagicMock()
        mock_require_member.return_value = MockMember()
        message = MockMessage(sender_id=uuid4())
        mock_get_message.return_value = message
        mock_get_report.return_value = MagicMock()

        with pytest.raises(HTTPException) as exc_info:
            report_message_service(
                room_id=uuid4(),
                message_id=message.id,
                user=MockUser(),
                reason=ChatMessageReportReason.HARASSMENT,
            )

        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
