import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
from datetime import datetime, timezone as tz
from fastapi import HTTPException
from starlette import status

# Import the app first so the full SQLAlchemy model registry is configured
# before any model instantiation below triggers mapper configuration.
import pecha_api.app  # noqa: F401

from pecha_api.chat.enums import ChatMessageReportReason, ChatMessageReportSource
from pecha_api.chat.moderation_service import (
    ALLOWED_TERMS,
    INAPPROPRIATE_LANGUAGE,
    INAPPROPRIATE_LANGUAGE_MESSAGE,
    contains_inappropriate_language,
)
from pecha_api.chat.message_service import (
    send_direct_message_service,
    send_group_message_service,
)

CLEAN_MESSAGE = "Hello, how are you today?"
PROFANE_MESSAGE = "well shit happens"


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


class TestContainsInappropriateLanguage:

    def test_detects_profanity(self):
        assert contains_inappropriate_language(PROFANE_MESSAGE) is True

    def test_allows_clean_text(self):
        assert contains_inappropriate_language(CLEAN_MESSAGE) is False


def _profanity_error(exc_info):
    """Assert the exception carries the structured INAPPROPRIATE_LANGUAGE payload."""
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    detail = exc_info.value.detail
    assert detail["success"] is False
    assert detail["code"] == INAPPROPRIATE_LANGUAGE
    assert detail["message"] == INAPPROPRIATE_LANGUAGE_MESSAGE


class TestSendMessageProfanityFiltering:

    @patch('pecha_api.chat.moderation_service.create_report')
    @patch('pecha_api.chat.moderation_service.get_unresolved_automatic_report')
    @patch('pecha_api.chat.message_service.touch_room')
    @patch('pecha_api.chat.message_service.create_message')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service.resolve_or_create_group_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_clean_message_accepted_and_no_report_created(
        self, mock_session, mock_resolve, mock_require_member,
        mock_create_message, mock_touch, mock_get_auto_report, mock_create_report,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MagicMock(id=uuid4())
        mock_resolve.return_value = room
        user = MockUser()
        mock_require_member.return_value = MockMember(room_id=room.id, user_id=user.id)
        mock_create_message.return_value = MockMessage(
            sender=user, sender_id=user.id, room_id=room.id, body=CLEAN_MESSAGE
        )

        result = send_group_message_service(group_id=uuid4(), user=user, body=CLEAN_MESSAGE)

        assert result.body == CLEAN_MESSAGE
        mock_create_message.assert_called_once()
        mock_get_auto_report.assert_not_called()
        mock_create_report.assert_not_called()

    @patch('pecha_api.chat.moderation_service.create_report')
    @patch('pecha_api.chat.moderation_service.get_unresolved_automatic_report')
    @patch('pecha_api.chat.message_service.enqueue_chat_message_notification')
    @patch('pecha_api.chat.message_service.touch_room')
    @patch('pecha_api.chat.message_service.create_message')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service.resolve_or_create_group_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_profane_group_message_rejected_and_not_saved(
        self, mock_session, mock_resolve, mock_require_member,
        mock_create_message, mock_touch, mock_enqueue,
        mock_get_auto_report, mock_create_report,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MagicMock(id=uuid4())
        mock_resolve.return_value = room
        user = MockUser()
        mock_require_member.return_value = MockMember(room_id=room.id, user_id=user.id)
        mock_get_auto_report.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            send_group_message_service(group_id=uuid4(), user=user, body=PROFANE_MESSAGE)

        _profanity_error(exc_info)
        mock_create_message.assert_not_called()
        mock_touch.assert_not_called()
        mock_enqueue.assert_not_called()

    @patch('pecha_api.chat.moderation_service.create_report')
    @patch('pecha_api.chat.moderation_service.get_unresolved_automatic_report')
    @patch('pecha_api.chat.message_service.create_message')
    @patch('pecha_api.chat.message_service.resolve_or_create_private_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_profane_direct_message_rejected(
        self, mock_session, mock_resolve, mock_create_message,
        mock_get_auto_report, mock_create_report,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_resolve.return_value = MagicMock(id=uuid4())
        mock_get_auto_report.return_value = None

        with pytest.raises(HTTPException) as exc_info:
            send_direct_message_service(receiver_id=uuid4(), user=MockUser(), body=PROFANE_MESSAGE)

        _profanity_error(exc_info)
        mock_create_message.assert_not_called()

    @patch('pecha_api.chat.moderation_service.create_report')
    @patch('pecha_api.chat.moderation_service.get_unresolved_automatic_report')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service.resolve_or_create_group_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_profane_message_creates_automatic_report(
        self, mock_session, mock_resolve, mock_require_member,
        mock_get_auto_report, mock_create_report,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MagicMock(id=uuid4())
        mock_resolve.return_value = room
        user = MockUser()
        mock_require_member.return_value = MockMember(room_id=room.id, user_id=user.id)
        mock_get_auto_report.return_value = None

        with pytest.raises(HTTPException):
            send_group_message_service(group_id=uuid4(), user=user, body=PROFANE_MESSAGE)

        mock_create_report.assert_called_once()
        report = mock_create_report.call_args.kwargs["report"]
        assert report.reported_user_id == user.id
        assert report.room_id == room.id
        assert report.source == ChatMessageReportSource.AUTOMATIC.value
        assert report.reason == ChatMessageReportReason.INAPPROPRIATE_LANGUAGE.value
        assert report.message_text == PROFANE_MESSAGE
        assert report.message_id is None
        assert report.reporter_id is None

    @patch('pecha_api.chat.moderation_service.create_report')
    @patch('pecha_api.chat.moderation_service.get_unresolved_automatic_report')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service.resolve_or_create_group_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_retried_profane_message_does_not_duplicate_report(
        self, mock_session, mock_resolve, mock_require_member,
        mock_get_auto_report, mock_create_report,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MagicMock(id=uuid4())
        mock_resolve.return_value = room
        user = MockUser()
        mock_require_member.return_value = MockMember(room_id=room.id, user_id=user.id)
        mock_get_auto_report.return_value = MagicMock()  # report already on file

        with pytest.raises(HTTPException) as exc_info:
            send_group_message_service(group_id=uuid4(), user=user, body=PROFANE_MESSAGE)

        _profanity_error(exc_info)
        mock_create_report.assert_not_called()

    @patch('pecha_api.chat.moderation_service.create_report')
    @patch('pecha_api.chat.moderation_service.get_unresolved_automatic_report')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service.resolve_or_create_group_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    def test_concurrent_duplicate_report_insert_is_swallowed(
        self, mock_session, mock_resolve, mock_require_member,
        mock_get_auto_report, mock_create_report,
    ):
        """A concurrent identical submission that wins the race past the
        lookup hits the partial unique index; the losing insert must roll
        back quietly while the message is still rejected."""
        from sqlalchemy.exc import IntegrityError

        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        room = MagicMock(id=uuid4())
        mock_resolve.return_value = room
        user = MockUser()
        mock_require_member.return_value = MockMember(room_id=room.id, user_id=user.id)
        mock_get_auto_report.return_value = None
        mock_create_report.side_effect = IntegrityError("stmt", {}, Exception("dup"))

        with pytest.raises(HTTPException) as exc_info:
            send_group_message_service(group_id=uuid4(), user=user, body=PROFANE_MESSAGE)

        _profanity_error(exc_info)
        db.rollback.assert_called_once()


class TestProfanityRestEndpoint:

    @patch('pecha_api.chat.moderation_service.create_report')
    @patch('pecha_api.chat.moderation_service.get_unresolved_automatic_report')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service.resolve_or_create_group_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_rest_send_returns_error_code_and_message(
        self, mock_validate, mock_session, mock_resolve, mock_require_member,
        mock_get_auto_report, mock_create_report,
    ):
        from pecha_api.app import api
        from fastapi.testclient import TestClient

        mock_validate.return_value = MockUser()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_resolve.return_value = MagicMock(id=uuid4())
        mock_require_member.return_value = MockMember()
        mock_get_auto_report.return_value = None

        client = TestClient(api)
        response = client.post(
            f"/chat/groups/{uuid4()}/messages",
            json={"body": PROFANE_MESSAGE},
            headers={"Authorization": "Bearer test-token"},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        detail = response.json()["detail"]
        assert detail["success"] is False
        assert detail["code"] == INAPPROPRIATE_LANGUAGE
        assert detail["message"] == INAPPROPRIATE_LANGUAGE_MESSAGE
        mock_create_report.assert_called_once()


class TestProfanityWebSocket:

    @patch('pecha_api.chat.moderation_service.create_report')
    @patch('pecha_api.chat.moderation_service.get_unresolved_automatic_report')
    @patch('pecha_api.chat.message_service._require_active_member')
    @patch('pecha_api.chat.message_service.resolve_or_create_group_room')
    @patch('pecha_api.chat.message_service.SessionLocal')
    @patch('pecha_api.chat.service.resolve_or_create_group_room')
    @patch('pecha_api.db.database.SessionLocal')
    @patch('pecha_api.chat.views.get_broadcaster')
    @patch('pecha_api.chat.views.validate_and_extract_user_details')
    def test_profane_ws_message_rejected_and_not_broadcast(
        self, mock_validate, mock_get_broadcaster, mock_ws_session,
        mock_ws_resolve, mock_svc_session, mock_svc_resolve,
        mock_require_member, mock_get_auto_report, mock_create_report,
    ):
        import asyncio
        from pecha_api.app import api
        from fastapi.testclient import TestClient

        user = MockUser()
        room = MagicMock(id=uuid4())
        mock_validate.return_value = user
        mock_ws_session.return_value.__enter__.return_value = MagicMock()
        mock_ws_resolve.return_value = room
        mock_svc_session.return_value.__enter__.return_value = MagicMock()
        mock_svc_resolve.return_value = room
        mock_require_member.return_value = MockMember(room_id=room.id, user_id=user.id)
        mock_get_auto_report.return_value = None

        class FakeSubscriber:
            """A live channel with nothing published on it: get() waits.

            Returning instead would mean the channel stopped, which closes the
            socket, and this case needs it open long enough to be answered."""

            async def get(self):
                await asyncio.Event().wait()

        broadcaster = MagicMock()
        broadcaster.subscribe_to_room = AsyncMock(return_value=FakeSubscriber())
        broadcaster.unsubscribe_from_room = AsyncMock()
        broadcaster.add_connection = AsyncMock()
        broadcaster.remove_connection = AsyncMock()
        broadcaster.broadcast_presence = AsyncMock()
        broadcaster.broadcast_typing = AsyncMock()
        broadcaster.broadcast_message = AsyncMock()
        mock_get_broadcaster.return_value = broadcaster

        client = TestClient(api)
        with client.websocket_connect(
            f"/chat/live?token=test-token&group_id={uuid4()}"
        ) as websocket:
            room_info = websocket.receive_json()
            assert room_info["type"] == "room_info"

            websocket.send_json({"type": "message", "body": PROFANE_MESSAGE})
            error = websocket.receive_json()

            assert error["type"] == "error"
            assert error["success"] is False
            assert error["code"] == INAPPROPRIATE_LANGUAGE
            assert error["message"] == INAPPROPRIATE_LANGUAGE_MESSAGE

        broadcaster.broadcast_message.assert_not_called()
        mock_create_report.assert_called_once()


# --- Allowlisted community vocabulary -------------------------------------
# The bundled English wordlist flags terms that are ordinary vocabulary here.
# These assert the allowlist is applied and that profanity still gets caught.

@pytest.mark.parametrize("term", list(ALLOWED_TERMS))
def test_allowlisted_term_is_not_profanity(term):
    assert contains_inappropriate_language(term) is False


@pytest.mark.parametrize("message", [
    "Do Buddhists believe in god?",
    "the hell realms are described in the Abhidharma",
    "the first precept is not to kill",
    "lust is one of the three poisons",
    "I received the oral transmission and the wang from Rinpoche",
    "Tathagatagarbha means the womb of the Buddha",
    "the third precept concerns sexual misconduct",
    "the fifth precept covers alcohol and weed",
    "Lama Wang Chuk will teach tonight",
    "I am gay and new to this sangha",
    "please put the pot on the shrine",
])
def test_community_vocabulary_is_allowed(message):
    assert contains_inappropriate_language(message) is False


@pytest.mark.parametrize("message", [
    PROFANE_MESSAGE,
    "fuck this",
    "you are an asshole",
    "what a bitch",
])
def test_genuine_profanity_is_still_blocked(message):
    assert contains_inappropriate_language(message) is True


def test_allowlist_is_actually_applied_to_the_wordset():
    """Guard against a library upgrade silently dropping `whitelist_words`.

    If the kwarg is renamed or ignored, the terms fall back into the active
    wordset and every message above starts being rejected again.
    """
    from better_profanity import profanity

    active = {str(word) for word in profanity.CENSOR_WORDSET}
    for term in ALLOWED_TERMS:
        assert term not in active, f"{term!r} is still censored; allowlist not applied"
    assert "fuck" in active, "wordlist did not load at all"
