import pytest
from datetime import datetime, timedelta, timezone as tz
from unittest.mock import MagicMock, patch
from uuid import uuid4

from fastapi import HTTPException
from starlette import status

# Import the app first so the full SQLAlchemy model registry is configured
# before any ChatRoom()/ChatMessage() instantiation below triggers mapper configuration.
import pecha_api.app  # noqa: F401

from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.message_service import (
    _validate_message_type,
    list_message_prayers_service,
    pray_for_messages_service,
    unpray_message_service,
)
from pecha_api.chat.response_models import PrayForMessagesRequest
from pecha_api.chat.service import build_message_dto

MODULE = "pecha_api.chat.message_service"


class MockUser:
    def __init__(self, user_id=None, email="user@example.com", firstname="Alice"):
        self.id = user_id or uuid4()
        self.email = email
        self.firstname = firstname
        self.lastname = None
        self.avatar_url = None


class MockMessage:
    def __init__(self, message_id=None, room_id=None, sender=None, message_type="PRAYER"):
        self.id = message_id or uuid4()
        self.room_id = room_id or uuid4()
        self.sender = sender or MockUser()
        self.sender_id = self.sender.id
        self.body = "Please pray for my mother"
        self.message_type = message_type
        self.created_at = datetime.now(tz.utc)
        self.deleted_at = None
        self.parent = None
        self.parent_message_id = None


class MockPrayer:
    def __init__(self, message_id=None, user=None):
        self.id = uuid4()
        self.message_id = message_id or uuid4()
        self.user = user or MockUser()
        self.user_id = self.user.id
        self.created_at = datetime.now(tz.utc)


def _session(mock_session):
    mock_session.return_value.__enter__.return_value = MagicMock()


class TestPrayerRequestPlacement:
    """A prayer request needs a congregation, so DMs reject it."""

    def test_prayer_allowed_in_a_group_room(self):
        room = MagicMock(group_id=uuid4(), event_id=None, sender_id=None, receiver_id=None)

        assert (
            _validate_message_type(room=room, message_type="PRAYER") == "PRAYER"
        )

    def test_prayer_allowed_in_an_event_room(self):
        room = MagicMock(group_id=None, event_id=uuid4(), sender_id=None, receiver_id=None)

        assert (
            _validate_message_type(room=room, message_type="PRAYER") == "PRAYER"
        )

    def test_prayer_rejected_in_a_dm(self):
        room = MagicMock(group_id=None, event_id=None, sender_id=uuid4(), receiver_id=uuid4())

        with pytest.raises(HTTPException) as exc_info:
            _validate_message_type(room=room, message_type="PRAYER")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "PRAYER_NOT_ALLOWED_IN_DM"

    def test_text_allowed_everywhere(self):
        room = MagicMock(group_id=None, event_id=None, sender_id=uuid4(), receiver_id=uuid4())

        assert _validate_message_type(room=room, message_type="TEXT") == "TEXT"

    def test_unknown_type_rejected(self):
        room = MagicMock(group_id=uuid4(), event_id=None, sender_id=None, receiver_id=None)

        with pytest.raises(HTTPException) as exc_info:
            _validate_message_type(room=room, message_type="SHOUT")

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


class TestPrayerBatchRequestValidation:

    def test_rejects_empty_selection(self):
        with pytest.raises(ValueError):
            PrayForMessagesRequest(message_ids=[])

    def test_drops_duplicate_ids_keeping_order(self):
        first, second = uuid4(), uuid4()

        request = PrayForMessagesRequest(message_ids=[first, second, first])

        assert request.message_ids == [first, second]

    def test_rejects_more_than_fifty(self):
        with pytest.raises(ValueError):
            PrayForMessagesRequest(message_ids=[uuid4() for _ in range(51)])


class TestPrayForMessagesService:

    @patch(f"{MODULE}.enqueue_prayer_notification")
    @patch(f"{MODULE}.get_prayer_user_ids_map")
    @patch(f"{MODULE}.get_prayer_counts_map")
    @patch(f"{MODULE}.add_prayers_ignoring_duplicates")
    @patch(f"{MODULE}.get_message_by_id")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_prays_for_several_selected_requests_at_once(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_add_prayers,
        mock_counts,
        mock_user_ids,
        mock_enqueue,
    ):
        _session(mock_session)
        room_id = uuid4()
        user = MockUser()
        first = MockMessage(room_id=room_id)
        second = MockMessage(room_id=room_id)
        mock_get_message.side_effect = lambda db, message_id, room_id: (
            first if message_id == first.id else second
        )
        prayer_ids = [uuid4(), uuid4()]
        mock_add_prayers.return_value = [
            (first.id, prayer_ids[0]),
            (second.id, prayer_ids[1]),
        ]
        mock_counts.return_value = {first.id: 3, second.id: 1}
        mock_user_ids.return_value = {first.id: [user.id], second.id: [user.id]}

        result = pray_for_messages_service(
            room_id=room_id, user=user, message_ids=[first.id, second.id]
        )

        assert [p.message_id for p in result.response.prayers] == [first.id, second.id]
        assert [p.prayer_count for p in result.response.prayers] == [3, 1]
        assert all(p.prayed_by_me for p in result.response.prayers)
        assert all(p.created for p in result.response.prayers)
        assert result.room_id == room_id
        # One notification per prayer actually created.
        assert mock_enqueue.call_count == 2

    @patch(f"{MODULE}.enqueue_prayer_notification")
    @patch(f"{MODULE}.get_prayer_user_ids_map", return_value={})
    @patch(f"{MODULE}.get_prayer_counts_map")
    @patch(f"{MODULE}.add_prayers_ignoring_duplicates", return_value=[])
    @patch(f"{MODULE}.get_message_by_id")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_praying_again_is_idempotent_and_raises_no_notification(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        _mock_add_prayers,
        mock_counts,
        _mock_user_ids,
        mock_enqueue,
    ):
        _session(mock_session)
        message = MockMessage()
        mock_get_message.return_value = message
        mock_counts.return_value = {message.id: 7}

        result = pray_for_messages_service(
            room_id=message.room_id, user=MockUser(), message_ids=[message.id]
        )

        state = result.response.prayers[0]
        assert state.created is False
        assert state.prayed_by_me is True
        assert state.prayer_count == 7
        mock_enqueue.assert_not_called()

    @patch(f"{MODULE}.enqueue_prayer_notification")
    @patch(f"{MODULE}.get_prayer_user_ids_map", return_value={})
    @patch(f"{MODULE}.get_prayer_counts_map")
    @patch(f"{MODULE}.add_prayers_ignoring_duplicates")
    @patch(f"{MODULE}.get_message_by_id")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_skips_ids_that_are_not_live_prayer_requests(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_add_prayers,
        mock_counts,
        _mock_user_ids,
        _mock_enqueue,
    ):
        """A request deleted between rendering and confirming must not cost the
        user the rest of their selection."""
        _session(mock_session)
        prayer = MockMessage()
        plain = MockMessage(message_type="TEXT")
        gone_id = uuid4()

        def lookup(db, message_id, room_id):
            if message_id == prayer.id:
                return prayer
            if message_id == plain.id:
                return plain
            return None

        mock_get_message.side_effect = lookup
        mock_add_prayers.return_value = []
        mock_counts.return_value = {prayer.id: 1}

        result = pray_for_messages_service(
            room_id=prayer.room_id,
            user=MockUser(),
            message_ids=[prayer.id, plain.id, gone_id],
        )

        assert [p.message_id for p in result.response.prayers] == [prayer.id]
        assert mock_add_prayers.call_args.kwargs["message_ids"] == [prayer.id]

    @patch(f"{MODULE}.get_message_by_id", return_value=None)
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_404_when_nothing_in_the_selection_is_prayable(
        self, mock_session, _mock_room, _mock_member, _mock_get_message
    ):
        _session(mock_session)

        with pytest.raises(HTTPException) as exc_info:
            pray_for_messages_service(
                room_id=uuid4(), user=MockUser(), message_ids=[uuid4()]
            )

        assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    @patch(f"{MODULE}.enqueue_prayer_notification")
    @patch(f"{MODULE}.get_prayer_user_ids_map")
    @patch(f"{MODULE}.get_prayer_counts_map")
    @patch(f"{MODULE}.add_prayers_ignoring_duplicates")
    @patch(f"{MODULE}.get_message_by_id")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_broadcast_carries_count_and_user_ids_per_message(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_add_prayers,
        mock_counts,
        mock_user_ids,
        _mock_enqueue,
    ):
        """One payload for the whole selection, and no viewer-specific state in
        it - clients derive prayed_by_me from user_ids, as they do for reactions."""
        _session(mock_session)
        message = MockMessage()
        mock_get_message.return_value = message
        mock_add_prayers.return_value = []
        mock_counts.return_value = {message.id: 2}
        prayer_user_ids = [uuid4(), uuid4()]
        mock_user_ids.return_value = {message.id: prayer_user_ids}

        result = pray_for_messages_service(
            room_id=message.room_id, user=MockUser(), message_ids=[message.id]
        )

        assert result.broadcast == [
            {
                "message_id": str(message.id),
                "prayer_count": 2,
                "user_ids": [str(user_id) for user_id in prayer_user_ids],
            }
        ]
        assert "prayed_by_me" not in result.broadcast[0]


class TestUnprayMessageService:

    @patch(f"{MODULE}.get_prayer_user_ids_map", return_value={})
    @patch(f"{MODULE}.count_message_prayers", return_value=4)
    @patch(f"{MODULE}.remove_prayer")
    @patch(f"{MODULE}.get_prayer")
    @patch(f"{MODULE}.get_message_by_id_any_room")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_removes_the_callers_prayer(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_get_prayer,
        mock_remove,
        _mock_count,
        _mock_user_ids,
    ):
        _session(mock_session)
        message = MockMessage()
        mock_get_message.return_value = message
        prayer = MockPrayer(message_id=message.id)
        mock_get_prayer.return_value = prayer

        result = unpray_message_service(message_id=message.id, user=MockUser())

        assert mock_remove.call_args.kwargs["prayer"] is prayer
        assert result.response.prayers[0].prayed_by_me is False
        assert result.response.prayers[0].prayer_count == 4
        assert result.room_id == message.room_id

    @patch(f"{MODULE}.get_prayer_user_ids_map", return_value={})
    @patch(f"{MODULE}.count_message_prayers", return_value=0)
    @patch(f"{MODULE}.remove_prayer")
    @patch(f"{MODULE}.get_prayer", return_value=None)
    @patch(f"{MODULE}.get_message_by_id_any_room")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_unpraying_twice_is_a_noop(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        _mock_get_prayer,
        mock_remove,
        _mock_count,
        _mock_user_ids,
    ):
        _session(mock_session)
        mock_get_message.return_value = MockMessage()

        unpray_message_service(message_id=uuid4(), user=MockUser())

        mock_remove.assert_not_called()

    @patch(f"{MODULE}.get_message_by_id_any_room")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_rejects_a_message_that_is_not_a_prayer_request(
        self, mock_session, _mock_room, _mock_member, mock_get_message
    ):
        _session(mock_session)
        mock_get_message.return_value = MockMessage(message_type="TEXT")

        with pytest.raises(HTTPException) as exc_info:
            unpray_message_service(message_id=uuid4(), user=MockUser())

        assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
        assert exc_info.value.detail == "NOT_A_PRAYER_REQUEST"


class TestListMessagePrayersService:

    @patch(f"{MODULE}.list_message_prayers")
    @patch(f"{MODULE}.get_message_by_id_any_room")
    @patch(f"{MODULE}._require_active_member")
    @patch(f"{MODULE}._get_room_or_404")
    @patch(f"{MODULE}.SessionLocal")
    def test_lists_who_prayed(
        self,
        mock_session,
        _mock_room,
        _mock_member,
        mock_get_message,
        mock_list,
    ):
        _session(mock_session)
        message = MockMessage()
        mock_get_message.return_value = message
        praying_user = MockUser(email="bob@example.com", firstname="Bob")
        mock_list.return_value = ([MockPrayer(message.id, praying_user)], 1)

        response = list_message_prayers_service(
            message_id=message.id, user=MockUser(), skip=0, limit=20
        )

        assert response.total == 1
        assert response.message_id == message.id
        assert response.prayers[0].user_id == praying_user.id
        assert response.prayers[0].email == "bob@example.com"
        assert response.prayers[0].name == "Bob"


class TestPrayerFieldsOnMessageDTO:

    def test_prayer_fields_omitted_for_a_text_message(self):
        dto = build_message_dto(MockMessage(message_type="TEXT"))
        payload = dto.model_dump()

        assert dto.message_type == "TEXT"
        assert "prayer_count" not in payload
        assert "prayed_by_me" not in payload
        assert "recent_prayers" not in payload

    def test_prayer_fields_present_for_a_prayer_request(self):
        praying_user = MockUser(email="bob@example.com", firstname="Bob")

        dto = build_message_dto(
            MockMessage(message_type="PRAYER"),
            prayer_count=12,
            prayed_by_me=True,
            recent_prayers=[praying_user],
        )
        payload = dto.model_dump()

        assert payload["message_type"] == "PRAYER"
        assert payload["prayer_count"] == 12
        assert payload["prayed_by_me"] is True
        assert payload["recent_prayers"][0]["user_id"] == praying_user.id

    def test_enum_valued_message_type_serializes_as_a_string(self):
        message = MockMessage(message_type=ChatMessageType.PRAYER)

        dto = build_message_dto(message)

        assert dto.message_type == "PRAYER"

    def test_message_type_defaults_to_text_when_absent(self):
        """Rows written before the column existed read back as TEXT."""
        message = MockMessage()
        message.message_type = None

        dto = build_message_dto(message)

        assert dto.message_type == "TEXT"


class TestPrayerNotificationCoalescing:

    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=900)
    @patch("pecha_api.chat.notification_dispatch_service.has_dispatched_prayer_since")
    @patch("pecha_api.chat.notification_dispatch_service.get_message_by_id_any_room")
    def test_self_pray_raises_no_notification(
        self, mock_get_message, _mock_recent, _mock_get_int
    ):
        from pecha_api.chat.notification_dispatch_service import _should_notify_prayer

        requester = MockUser()
        message = MockMessage(sender=requester)
        mock_get_message.return_value = message
        prayer = MockPrayer(message_id=message.id, user=requester)

        assert _should_notify_prayer(db=MagicMock(), prayer=prayer) is False

    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=900)
    @patch(
        "pecha_api.chat.notification_dispatch_service.has_dispatched_prayer_since",
        return_value=True,
    )
    @patch("pecha_api.chat.notification_dispatch_service.get_message_by_id_any_room")
    def test_second_prayer_inside_the_window_is_folded_in(
        self, mock_get_message, _mock_recent, _mock_get_int
    ):
        from pecha_api.chat.notification_dispatch_service import _should_notify_prayer

        mock_get_message.return_value = MockMessage()

        assert _should_notify_prayer(db=MagicMock(), prayer=MockPrayer()) is False

    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=900)
    @patch(
        "pecha_api.chat.notification_dispatch_service.has_dispatched_prayer_since",
        return_value=False,
    )
    @patch("pecha_api.chat.notification_dispatch_service.get_message_by_id_any_room")
    def test_first_prayer_notifies_the_requester(
        self, mock_get_message, _mock_recent, _mock_get_int
    ):
        from pecha_api.chat.notification_dispatch_service import _should_notify_prayer

        mock_get_message.return_value = MockMessage()

        assert _should_notify_prayer(db=MagicMock(), prayer=MockPrayer()) is True

    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=900)
    @patch(
        "pecha_api.chat.notification_dispatch_service.has_dispatched_prayer_since",
        return_value=False,
    )
    @patch("pecha_api.chat.notification_dispatch_service.get_message_by_id_any_room")
    def test_window_is_measured_back_from_now(
        self, mock_get_message, mock_recent, _mock_get_int
    ):
        from pecha_api.chat.notification_dispatch_service import _should_notify_prayer

        mock_get_message.return_value = MockMessage()

        _should_notify_prayer(db=MagicMock(), prayer=MockPrayer())

        since = mock_recent.call_args.kwargs["since"]
        expected = datetime.now(tz.utc) - timedelta(seconds=900)
        assert abs((since - expected).total_seconds()) < 5

    @patch("pecha_api.chat.notification_dispatch_service.mark_prayer_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_chat_notification_message")
    @patch("pecha_api.chat.notification_dispatch_service._should_notify_prayer", return_value=False)
    @patch("pecha_api.chat.notification_dispatch_service.get_prayer_by_id")
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    @patch(
        "pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured",
        return_value=True,
    )
    def test_suppressed_prayer_is_marked_so_the_reconciler_lets_it_go(
        self,
        _mock_configured,
        mock_session,
        mock_get_prayer,
        _mock_should,
        mock_send,
        mock_mark,
    ):
        from pecha_api.chat.notification_dispatch_service import (
            SUPPRESSED_SQS_MESSAGE_ID,
            enqueue_prayer_notification,
        )

        mock_session.return_value.__enter__.return_value = MagicMock()
        prayer = MockPrayer()
        mock_get_prayer.return_value = prayer

        assert enqueue_prayer_notification(prayer.id) is None
        mock_send.assert_not_called()
        assert mock_mark.call_args.kwargs["sqs_message_id"] == SUPPRESSED_SQS_MESSAGE_ID
