import json
from types import SimpleNamespace
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

import pecha_api.app  # noqa: F401

from pecha_api.chat.message_service import send_direct_message_service, send_group_message_service
from pecha_api.chat.notification_dispatch_service import (
    SUPPRESSED_SQS_MESSAGE_ID,
    enqueue_chat_message_notification,
    reconcile_undispatched_chat_notifications,
)
from pecha_api.chat.notification_service import (
    _build_notification_copy,
    _build_prayer_notification_copy,
    _count_held_prayer_requests,
    _preview_body,
    deactivate_push_device_service,
    get_chat_notification_targets,
    get_prayer_notification_targets,
)
from pecha_api.chat.sqs_client import (
    CHAT_MESSAGE_CREATED_EVENT,
    CHAT_NOTIFICATION_EVENT_VERSION,
    build_chat_notification_event_body,
)
from pecha_api.notification.notification_preference_enums import NotificationType


class MockUser:
    def __init__(self, user_id=None, email="user@example.com", firstname="Alice", lastname="Doe", avatar_url=None):
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
    def __init__(self, sender=None, sender_id=None, room_id=None, body="Hello", room=None, message_type="TEXT"):
        self.id = uuid4()
        self.room_id = room_id or uuid4()
        self.sender_id = sender_id or uuid4()
        self.sender = sender or MockUser(user_id=self.sender_id)
        self.body = body
        self.message_type = message_type
        self.created_at = datetime.now(timezone.utc)
        self.deleted_at = None
        self.room = room
        self.notification_sqs_message_id = None
        self.notification_dispatched_at = None


class MockRoom:
    def __init__(self, group_id=None, sender_id=None, receiver_id=None, name="Room", img_url=None):
        self.id = uuid4()
        self.group_id = group_id
        self.sender_id = sender_id
        self.receiver_id = receiver_id
        self.name = name
        self.img_url = img_url


class MockDevice:
    def __init__(self, user_id, token="tok", platform="ANDROID", is_active=True):
        self.id = uuid4()
        self.user_id = user_id
        self.token = token
        self.platform = platform
        self.is_active = is_active


class TestPreviewAndCopy:
    def test_preview_truncates(self):
        assert _preview_body("hello world", 5) == "hell…"
        assert _preview_body("hi", 10) == "hi"

    def test_private_copy_uses_sender_name(self):
        title, body = _build_notification_copy(
            room_name="Alice & Bob",
            sender_name="Alice Doe",
            message_body="Hello there",
        )
        assert title == "Alice Doe"
        assert body == "Hello there"

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_group_copy_is_titled_with_the_sender_and_carries_the_message(self, _get_int):
        title, body = _build_notification_copy(
            room_name="Sangha",
            sender_name="Doe",
            message_body="Hello group",
        )
        assert title == "Doe"
        assert body == "Hello group"

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_prayer_copy_names_the_requester_and_drops_the_room(self, _get_int):
        """With the room's image attached, the name is redundant."""
        title, body = _build_notification_copy(
            room_name="Dzongsar Drolma Bumtshok",
            sender_name="Tenzin Youdon",
            message_body="For my niece Sarah, that her treatment is swift.",
            message_type="PRAYER",
            has_image=True,
        )
        assert title == "Tenzin Youdon is requesting a prayer 🙏"
        assert body == "For my niece Sarah, that her treatment is swift."
        assert "Dzongsar" not in title
        assert "Dzongsar" not in body

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_prayer_without_an_image_keeps_the_room_name(self, _get_int):
        """Nothing else would say which sangha the prayer came from."""
        title, body = _build_notification_copy(
            room_name="Dzongsar Drolma Bumtshok",
            sender_name="Tenzin Youdon",
            message_body="For my niece Sarah, that her treatment is swift.",
            message_type="PRAYER",
            has_image=False,
        )
        assert title == "Tenzin Youdon is requesting a prayer 🙏"
        assert body == (
            "Dzongsar Drolma Bumtshok: For my niece Sarah, that her treatment is swift."
        )

    @patch("pecha_api.chat.notification_service.get_int", return_value=20)
    def test_prayer_body_still_truncates(self, _get_int):
        _, body = _build_notification_copy(
            room_name="Sangha",
            sender_name="Alice Doe",
            message_body="A prayer request far longer than the preview allows",
            message_type="PRAYER",
            has_image=True,
        )
        assert len(body) == 20
        assert body.endswith("…")

    @patch("pecha_api.chat.notification_service.get_int", return_value=20)
    def test_prayer_preview_truncates_around_the_room_name(self, _get_int):
        """The limit governs the excerpt; the room prefix sits outside it, the
        way the group-chat sender prefix already does."""
        _, body = _build_notification_copy(
            room_name="Sangha",
            sender_name="Alice Doe",
            message_body="A prayer request far longer than the preview allows",
            message_type="PRAYER",
            has_image=False,
        )
        assert body.startswith("Sangha: ")
        assert len(body.removeprefix("Sangha: ")) == 20


class TestCountHeldPrayerRequests:
    SENT = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
    NOW = datetime(2026, 9, 25, 10, 20, tzinfo=timezone.utc)

    @staticmethod
    def _record(at):
        return SimpleNamespace(dispatched_at=at, created_at=at - timedelta(seconds=2))

    @patch("pecha_api.chat.notification_service.count_suppressed_prayer_requests", return_value=2)
    @patch("pecha_api.chat.notification_service.last_dispatched_prayer_request")
    def test_counts_from_the_previous_push(self, mock_last_sent, mock_count):
        mock_last_sent.return_value = self._record(self.SENT)

        assert _count_held_prayer_requests(
            db=MagicMock(), room_id=uuid4(), message_id=uuid4(), dispatched_at=self.NOW
        ) == 2
        # The suppression clock at both ends, so each held request lands in
        # exactly one window.
        assert mock_count.call_args.kwargs["since"] == self.SENT

    @patch("pecha_api.chat.notification_service.count_suppressed_prayer_requests", return_value=1)
    @patch("pecha_api.chat.notification_service.last_dispatched_prayer_request", return_value=None)
    def test_a_room_that_never_pushed_counts_everything_held(self, _last_sent, mock_count):
        assert _count_held_prayer_requests(
            db=MagicMock(), room_id=uuid4(), message_id=uuid4(), dispatched_at=self.NOW
        ) == 1
        assert mock_count.call_args.kwargs["since"] is None

    @patch("pecha_api.chat.notification_service.count_suppressed_prayer_requests", return_value=0)
    @patch("pecha_api.chat.notification_service.last_dispatched_prayer_request", return_value=None)
    def test_the_window_closes_at_this_push(self, _last_sent, mock_count):
        """A request suppressed while the worker is building this push belongs
        to the next one, not to this one and then the next one again."""
        _count_held_prayer_requests(
            db=MagicMock(), room_id=uuid4(), message_id=uuid4(), dispatched_at=self.NOW
        )

        assert mock_count.call_args.kwargs["until"] == self.NOW

    @patch("pecha_api.chat.notification_service.count_suppressed_prayer_requests", return_value=0)
    @patch("pecha_api.chat.notification_service.last_dispatched_prayer_request", return_value=None)
    def test_an_unstamped_push_bounds_at_now(self, _last_sent, mock_count):
        """The worker beat the backend's mark. now() is the same instant either
        way, and the window still has to close somewhere."""
        before = datetime.now(timezone.utc)

        _count_held_prayer_requests(
            db=MagicMock(), room_id=uuid4(), message_id=uuid4(), dispatched_at=None
        )

        assert mock_count.call_args.kwargs["until"] >= before

    @patch("pecha_api.chat.notification_service.count_suppressed_prayer_requests", return_value=0)
    @patch("pecha_api.chat.notification_service.last_dispatched_prayer_request", return_value=None)
    def test_the_search_for_the_previous_push_stops_at_this_one(self, mock_last_sent, mock_count):
        """Both ends of the window come off this message's own moment.

        The worker is not guaranteed to reach a message before the next prayer
        request pushes, so the room's latest push can be one that went out
        after this message did. Taken as the window's start it would sit past
        its end, the count would come out zero, and the requests this push
        promised to carry would be announced by no push at all.
        """
        _count_held_prayer_requests(
            db=MagicMock(), room_id=uuid4(), message_id=uuid4(), dispatched_at=self.NOW
        )

        assert mock_last_sent.call_args.kwargs["before"] == self.NOW
        assert mock_count.call_args.kwargs["until"] == self.NOW

    @patch("pecha_api.chat.notification_service.count_suppressed_prayer_requests", return_value=0)
    @patch("pecha_api.chat.notification_service.last_dispatched_prayer_request", return_value=None)
    def test_an_unstamped_push_bounds_both_ends_at_the_same_now(self, mock_last_sent, mock_count):
        """One now(), read once: two readings could put the window's start
        after its end."""
        _count_held_prayer_requests(
            db=MagicMock(), room_id=uuid4(), message_id=uuid4(), dispatched_at=None
        )

        assert (
            mock_last_sent.call_args.kwargs["before"]
            == mock_count.call_args.kwargs["until"]
        )

    @patch("pecha_api.chat.notification_service.count_suppressed_prayer_requests", return_value=0)
    @patch("pecha_api.chat.notification_service.last_dispatched_prayer_request", return_value=None)
    def test_both_queries_exclude_the_message_being_sent(self, mock_last_sent, mock_count):
        """Without this the "last sent push" would be this very message, since
        the backend stamps it before the worker asks for targets, and the count
        would always come out zero."""
        message_id = uuid4()

        _count_held_prayer_requests(
            db=MagicMock(), room_id=uuid4(), message_id=message_id, dispatched_at=self.NOW
        )

        assert mock_last_sent.call_args.kwargs["exclude_message_id"] == message_id
        assert mock_count.call_args.kwargs["exclude_message_id"] == message_id


class TestHeldPrayerRequestCopy:
    """What the interval skipped, as words on the end of the body. The held
    requests are not listed - the room shows each one in full."""

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_no_suffix_when_nothing_was_held(self, _get_int):
        _, body = _build_notification_copy(
            room_name="Sangha",
            sender_name="Tenzin Youdon",
            message_body="For my niece Sarah.",
            message_type="PRAYER",
            has_image=True,
            held_count=0,
        )
        assert body == "For my niece Sarah."

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_one_held_request_reads_singular(self, _get_int):
        _, body = _build_notification_copy(
            room_name="Sangha",
            sender_name="Tenzin Youdon",
            message_body="For my niece Sarah.",
            message_type="PRAYER",
            has_image=True,
            held_count=1,
        )
        assert body == "For my niece Sarah. · +1 other prayer request"

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_several_held_requests_read_plural(self, _get_int):
        _, body = _build_notification_copy(
            room_name="Sangha",
            sender_name="Tenzin Youdon",
            message_body="For my niece Sarah.",
            message_type="PRAYER",
            has_image=True,
            held_count=3,
        )
        assert body == "For my niece Sarah. · +3 other prayer requests"

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_suffix_sits_after_the_room_name_prefix(self, _get_int):
        _, body = _build_notification_copy(
            room_name="Sangha",
            sender_name="Tenzin Youdon",
            message_body="For my niece Sarah.",
            message_type="PRAYER",
            has_image=False,
            held_count=3,
        )
        assert body == "Sangha: For my niece Sarah. · +3 other prayer requests"

    @patch("pecha_api.chat.notification_service.get_int", return_value=20)
    def test_suffix_survives_preview_truncation(self, _get_int):
        """The cap governs the request text. The count is the part that must
        survive - a long request is what gets the ellipsis."""
        _, body = _build_notification_copy(
            room_name="Sangha",
            sender_name="Tenzin Youdon",
            message_body="A prayer request far longer than the preview allows",
            message_type="PRAYER",
            has_image=True,
            held_count=4,
        )
        assert body.endswith(" · +4 other prayer requests")
        assert "…" in body

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_ordinary_chat_never_gets_the_suffix(self, _get_int):
        _, body = _build_notification_copy(
            room_name="Sangha",
            sender_name="Alice Doe",
            message_body="Hello group",
            held_count=5,
        )
        assert body == "Hello group"


class TestBuildEventBody:
    def test_builds_versioned_event(self):
        message_id = str(uuid4())
        body = build_chat_notification_event_body(message_id=message_id)
        assert body == {
            "event_type": CHAT_MESSAGE_CREATED_EVENT,
            "version": CHAT_NOTIFICATION_EVENT_VERSION,
            "message_id": message_id,
        }


class TestEnqueueChatMessageNotification:
    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_chat_notification_message")
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_enqueues_and_marks_dispatched(
        self,
        mock_session,
        _configured,
        mock_send,
        mock_mark,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_send.return_value = "sqs-1"
        message_id = uuid4()

        result = enqueue_chat_message_notification(message_id)

        assert result == "sqs-1"
        mock_send.assert_called_once()
        mock_mark.assert_called_once()

    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=False)
    def test_skips_when_unconfigured(self, _configured):
        assert enqueue_chat_message_notification(uuid4()) is None

    @patch("pecha_api.chat.notification_dispatch_service.send_chat_notification_message", side_effect=RuntimeError("boom"))
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=True)
    def test_returns_none_on_enqueue_failure(self, _configured, _send):
        assert enqueue_chat_message_notification(uuid4()) is None

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_prayer_notification_message", return_value="sqs-p")
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=0)
    @patch("pecha_api.chat.notification_dispatch_service.is_prayer_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=False)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_prayer_request_sends_with_only_the_prayer_queue_set(
        self, mock_session, _chat_configured, _prayer_configured, _get_int, mock_send, _mark
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()

        result = enqueue_chat_message_notification(
            uuid4(), message_type="PRAYER", room_id=uuid4()
        )

        assert result == "sqs-p"
        mock_send.assert_called_once()


class TestPrayerRequestNotificationInterval:
    """A prayer request goes to every member of the room, so ten requests in a
    busy sangha is ten notifications for everybody. One push per room per
    interval; the rest are held and travel as a count on the next one."""

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_prayer_notification_message", return_value="sqs-1")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request", return_value=None)
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=1140)
    @patch("pecha_api.chat.notification_dispatch_service.is_prayer_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_first_request_in_a_quiet_room_sends(
        self, mock_session, _configured, _get_int, _last_sent, mock_send, mock_mark
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()

        result = enqueue_chat_message_notification(
            uuid4(), message_type="PRAYER", room_id=uuid4()
        )

        assert result == "sqs-1"
        mock_send.assert_called_once()
        assert mock_mark.call_args.kwargs["sqs_message_id"] == "sqs-1"

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_prayer_notification_message")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request")
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=1140)
    @patch("pecha_api.chat.notification_dispatch_service.is_prayer_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_request_inside_the_interval_is_held(
        self, mock_session, _configured, _get_int, mock_last_sent, mock_send, mock_mark
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_last_sent.return_value = SimpleNamespace(
            dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=4),
            created_at=datetime.now(timezone.utc) - timedelta(minutes=4),
        )

        result = enqueue_chat_message_notification(
            uuid4(), message_type="PRAYER", room_id=uuid4()
        )

        assert result is None
        mock_send.assert_not_called()
        # Marked, not left undispatched: reconcile only retries rows that never
        # recorded an SQS id, so a held request stays held.
        assert mock_mark.call_args.kwargs["sqs_message_id"] == SUPPRESSED_SQS_MESSAGE_ID

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_prayer_notification_message", return_value="sqs-2")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request")
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=1140)
    @patch("pecha_api.chat.notification_dispatch_service.is_prayer_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_request_after_the_interval_sends(
        self, mock_session, _configured, _get_int, mock_last_sent, mock_send, _mark
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_last_sent.return_value = SimpleNamespace(
            dispatched_at=datetime.now(timezone.utc) - timedelta(minutes=20),
            created_at=datetime.now(timezone.utc) - timedelta(minutes=20),
        )

        result = enqueue_chat_message_notification(
            uuid4(), message_type="PRAYER", room_id=uuid4()
        )

        assert result == "sqs-2"
        mock_send.assert_called_once()

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_prayer_notification_message", return_value="sqs-3")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request")
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=0)
    @patch("pecha_api.chat.notification_dispatch_service.is_prayer_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_zero_disables_the_interval(
        self, mock_session, _configured, _get_int, mock_last_sent, mock_send, _mark
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_last_sent.return_value = SimpleNamespace(
            dispatched_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
        )

        result = enqueue_chat_message_notification(
            uuid4(), message_type="PRAYER", room_id=uuid4()
        )

        assert result == "sqs-3"
        mock_send.assert_called_once()
        mock_last_sent.assert_not_called()

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_prayer_notification_message")
    @patch("pecha_api.chat.notification_dispatch_service.send_chat_notification_message", return_value="sqs-4")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request")
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_ordinary_chat_is_never_gated(
        self, mock_session, _configured, mock_last_sent, mock_send, mock_prayer_send, _mark
    ):
        """A TEXT message costs no extra read to find out it is not a prayer,
        and stays on the chat queue."""
        mock_session.return_value.__enter__.return_value = MagicMock()

        result = enqueue_chat_message_notification(uuid4(), message_type="TEXT")

        assert result == "sqs-4"
        mock_last_sent.assert_not_called()
        mock_send.assert_called_once()
        mock_prayer_send.assert_not_called()

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_prayer_notification_message", return_value="sqs-5")
    @patch(
        "pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request",
        side_effect=RuntimeError("boom"),
    )
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=1140)
    @patch("pecha_api.chat.notification_dispatch_service.is_prayer_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_a_failed_check_lets_the_push_through(
        self, mock_session, _configured, _get_int, _last_sent, mock_send, _mark
    ):
        """One extra notification beats swallowing a prayer request."""
        mock_session.return_value.__enter__.return_value = MagicMock()

        result = enqueue_chat_message_notification(
            uuid4(), message_type="PRAYER", room_id=uuid4()
        )

        assert result == "sqs-5"
        mock_send.assert_called_once()

    @patch("pecha_api.chat.notification_dispatch_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_prayer_notification_message", return_value="sqs-6")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request", return_value=None)
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=1140)
    @patch("pecha_api.chat.notification_dispatch_service.is_prayer_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_a_missing_room_id_is_looked_up_rather_than_skipping_the_gate(
        self, mock_session, _configured, _get_int, mock_last_sent, mock_send, _mark, mock_get_message
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        message = MockMessage(message_type="PRAYER")
        mock_get_message.return_value = message

        enqueue_chat_message_notification(message.id, message_type="PRAYER")

        assert mock_last_sent.call_args.kwargs["room_id"] == message.room_id


class TestReconcileUndispatched:
    @patch("pecha_api.chat.notification_dispatch_service.enqueue_chat_message_notification", return_value="sqs-1")
    @patch("pecha_api.chat.notification_dispatch_service.list_undispatched_chat_notification_messages")
    @patch("pecha_api.chat.notification_dispatch_service.get_int", side_effect=lambda key: 60)
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_requeues_undispatched_messages(
        self,
        mock_session,
        _configured,
        _get_int,
        mock_list,
        mock_enqueue,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        message = MockMessage()
        mock_list.return_value = [message]

        assert reconcile_undispatched_chat_notifications() == 1
        # The type and room travel with the retry so a prayer request is
        # re-checked against the interval instead of becoming a second push.
        mock_enqueue.assert_called_once_with(
            message.id, message_type="TEXT", room_id=message.room_id
        )

    @patch("pecha_api.chat.notification_dispatch_service.enqueue_chat_message_notification", return_value="sqs-p")
    @patch("pecha_api.chat.notification_dispatch_service.list_undispatched_chat_notification_messages")
    @patch("pecha_api.chat.notification_dispatch_service.get_int", side_effect=lambda key: 60)
    @patch("pecha_api.chat.notification_dispatch_service.is_prayer_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=False)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_retries_only_prayer_requests_with_only_the_prayer_queue_set(
        self, mock_session, _chat_configured, _prayer_configured, _get_int, mock_list, mock_enqueue
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        message = MockMessage(message_type="PRAYER")
        mock_list.return_value = [message]

        assert reconcile_undispatched_chat_notifications() == 1
        assert mock_list.call_args.kwargs["message_type"] == "PRAYER"

    @patch("pecha_api.chat.notification_dispatch_service.list_undispatched_chat_notification_messages")
    @patch("pecha_api.chat.notification_dispatch_service.is_prayer_notification_sqs_configured", return_value=False)
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=False)
    def test_no_queue_does_nothing(self, _chat_configured, _prayer_configured, mock_list):
        assert reconcile_undispatched_chat_notifications() == 0
        mock_list.assert_not_called()


class TestPersistMessageEnqueues:
    @patch("pecha_api.chat.message_service.enqueue_chat_message_notification")
    @patch("pecha_api.chat.message_service.touch_room")
    @patch("pecha_api.chat.message_service.create_message")
    @patch("pecha_api.chat.message_service.resolve_or_create_private_room")
    @patch("pecha_api.chat.message_service.SessionLocal")
    def test_dm_send_enqueues_notification(
        self,
        mock_session,
        mock_resolve,
        mock_create_message,
        mock_touch,
        mock_enqueue,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MagicMock(id=uuid4())
        mock_resolve.return_value = room
        user = MockUser()
        created = MockMessage(sender=user, sender_id=user.id, room_id=room.id, body="Hey")
        mock_create_message.return_value = created

        result = send_direct_message_service(receiver_id=uuid4(), user=user, body="Hey")

        assert result.body == "Hey"
        mock_enqueue.assert_called_once_with(
            created.id, message_type="TEXT", room_id=room.id
        )

    @patch("pecha_api.chat.message_service.enqueue_chat_message_notification")
    @patch("pecha_api.chat.message_service.touch_room")
    @patch("pecha_api.chat.message_service.create_message")
    @patch("pecha_api.chat.message_service._require_active_member")
    @patch("pecha_api.chat.message_service.resolve_or_create_group_room")
    @patch("pecha_api.chat.message_service.SessionLocal")
    def test_group_send_enqueues_notification(
        self,
        mock_session,
        mock_resolve,
        mock_require,
        mock_create_message,
        mock_touch,
        mock_enqueue,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MagicMock(id=uuid4())
        mock_resolve.return_value = room
        user = MockUser()
        mock_require.return_value = MockMember(room_id=room.id, user_id=user.id)
        created = MockMessage(sender=user, sender_id=user.id, room_id=room.id, body="Hi")
        mock_create_message.return_value = created

        result = send_group_message_service(group_id=uuid4(), user=user, body="Hi")

        assert result.body == "Hi"
        mock_enqueue.assert_called_once_with(
            created.id, message_type="TEXT", room_id=room.id
        )


class TestGetChatNotificationTargets:
    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    @patch("pecha_api.chat.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.chat.notification_service.list_private_chat_recipient_user_ids")
    @patch("pecha_api.chat.notification_service.get_sender_display_name", return_value="Alice Doe")
    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_private_targets_exclude_sender_and_inactive_devices(
        self,
        mock_session,
        mock_get_message,
        mock_sender_name,
        mock_recipients,
        mock_devices,
        _get_int,
    ):
        sender_id = uuid4()
        peer_id = uuid4()
        db = MagicMock()
        # Chat is opt-in: the peer hears it only through a row turning it on.
        db.execute.return_value.all.return_value = [(peer_id, True, None, None)]
        mock_session.return_value.__enter__.return_value = db
        room = MockRoom(sender_id=sender_id, receiver_id=peer_id, name="DM")
        message = MockMessage(sender_id=sender_id, room=room, body="Hello")
        mock_get_message.return_value = message
        mock_recipients.return_value = [peer_id]
        device = MockDevice(user_id=peer_id, platform="IOS")
        mock_devices.return_value = {peer_id: [device]}

        result = get_chat_notification_targets(message_id=message.id)

        assert result.chat_kind == "PRIVATE"
        assert result.title == "Alice Doe"
        assert result.body == "Hello"
        assert len(result.recipients) == 1
        assert result.recipients[0].user_id == peer_id
        assert result.recipients[0].push_devices[0].platform == "ios"
        assert result.total == 1
        assert result.has_more is False

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    @patch("pecha_api.chat.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.chat.notification_service.list_private_chat_recipient_user_ids")
    @patch("pecha_api.chat.notification_service.get_sender_display_name", return_value="Alice Doe")
    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_private_target_with_no_saved_setting_gets_no_push(
        self,
        mock_session,
        mock_get_message,
        _sender_name,
        mock_recipients,
        mock_devices,
        _get_int,
    ):
        sender_id = uuid4()
        peer_id = uuid4()
        db = MagicMock()
        db.execute.return_value.all.return_value = []
        mock_session.return_value.__enter__.return_value = db
        room = MockRoom(sender_id=sender_id, receiver_id=peer_id, name="DM")
        mock_get_message.return_value = MockMessage(sender_id=sender_id, room=room, body="Hello")
        mock_recipients.return_value = [peer_id]
        mock_devices.return_value = {}

        result = get_chat_notification_targets(message_id=uuid4())

        assert result.recipients == []
        assert result.total == 0

    @patch("pecha_api.chat.notification_service._generate_presigned_url", return_value=None)
    @patch("pecha_api.chat.notification_service.get_group_avatar_key", return_value=None)
    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    @patch("pecha_api.chat.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.chat.notification_service.list_group_chat_recipient_user_ids")
    @patch("pecha_api.chat.notification_service.get_sender_short_name", return_value="Doe")
    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_group_targets_use_joiners_and_skip_users_without_devices(
        self,
        mock_session,
        mock_get_message,
        mock_sender_name,
        mock_recipients,
        mock_devices,
        _get_int,
        _avatar_key,
        _presign,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        sender_id = uuid4()
        joiner_with_device = uuid4()
        joiner_without_device = uuid4()
        group_id = uuid4()
        room = MockRoom(group_id=group_id, name="Sangha")
        message = MockMessage(sender_id=sender_id, room=room, body="Hello group")
        mock_get_message.return_value = message
        mock_recipients.return_value = ([joiner_with_device, joiner_without_device], 2)
        device = MockDevice(user_id=joiner_with_device)
        mock_devices.return_value = {joiner_with_device: [device]}

        result = get_chat_notification_targets(message_id=message.id, skip=0, limit=100)

        assert result.chat_kind == "GROUP"
        assert result.group_id == group_id
        assert result.title == "Doe"
        assert result.body == "Hello group"
        assert len(result.recipients) == 1
        assert result.recipients[0].user_id == joiner_with_device
        assert result.total == 2
        assert result.has_more is False
        assert (
            mock_recipients.call_args.kwargs["notification_type"]
            == NotificationType.CHAT_MESSAGE
        )

    @patch(
        "pecha_api.chat.notification_service._generate_presigned_url",
        return_value="https://example.com/event.png",
    )
    @patch("pecha_api.chat.notification_service._count_held_prayer_requests", return_value=0)
    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    @patch("pecha_api.chat.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.chat.notification_service.list_group_chat_recipient_user_ids")
    @patch("pecha_api.chat.notification_service.get_sender_display_name", return_value="Tenzin Youdon")
    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_prayer_request_targets_carry_prayer_copy_and_room_image(
        self,
        mock_session,
        mock_get_message,
        mock_sender_name,
        mock_recipients,
        mock_devices,
        _get_int,
        _held,
        mock_presign,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        sender_id = uuid4()
        joiner = uuid4()
        group_id = uuid4()
        room = MockRoom(
            group_id=group_id,
            name="Dzongsar Drolma Bumtshok",
            img_url="groups/avatar.png",
        )
        message = MockMessage(
            sender_id=sender_id,
            room=room,
            body="For my niece Sarah.",
            message_type="PRAYER",
        )
        mock_get_message.return_value = message
        mock_recipients.return_value = ([joiner], 1)
        mock_devices.return_value = {joiner: [MockDevice(user_id=joiner)]}

        result = get_chat_notification_targets(message_id=message.id)

        assert result.message_type == "PRAYER"
        assert result.title == "Tenzin Youdon is requesting a prayer 🙏"
        assert result.body == "For my niece Sarah."
        assert result.image_url == "https://example.com/event.png"
        mock_presign.assert_called_once_with("groups/avatar.png")

    @patch("pecha_api.chat.notification_service._generate_presigned_url", return_value=None)
    @patch("pecha_api.chat.notification_service._count_held_prayer_requests", return_value=0)
    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    @patch("pecha_api.chat.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.chat.notification_service.list_group_chat_recipient_user_ids")
    @patch("pecha_api.chat.notification_service.get_sender_display_name", return_value="Tenzin")
    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_group_prayer_request_ignores_chat_notification_setting(
        self,
        mock_session,
        mock_get_message,
        _sender_name,
        mock_recipients,
        mock_devices,
        _get_int,
        _held,
        _presign,
    ):
        """Chat pushes are opt-in; a member who never turned them on still
        hears a prayer request from their group."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        joiner = uuid4()
        room = MockRoom(group_id=uuid4(), name="Sangha")
        message = MockMessage(room=room, body="Please pray", message_type="PRAYER")
        mock_get_message.return_value = message
        mock_recipients.return_value = ([joiner], 1)
        mock_devices.return_value = {joiner: [MockDevice(user_id=joiner)]}

        result = get_chat_notification_targets(message_id=message.id)

        assert mock_recipients.call_args.kwargs["notification_type"] is None
        assert [recipient.user_id for recipient in result.recipients] == [joiner]

    @patch("pecha_api.chat.notification_service.get_event_by_id", return_value=None)
    @patch("pecha_api.chat.notification_service._generate_presigned_url", return_value=None)
    @patch("pecha_api.chat.notification_service._count_held_prayer_requests", return_value=0)
    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    @patch("pecha_api.chat.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.chat.notification_service.list_event_chat_recipient_user_ids")
    @patch("pecha_api.chat.notification_service.get_sender_display_name", return_value="Tenzin")
    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_event_prayer_request_ignores_chat_notification_setting(
        self,
        mock_session,
        mock_get_message,
        _sender_name,
        mock_recipients,
        mock_devices,
        _get_int,
        _held,
        _presign,
        _get_event,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        member = uuid4()
        room = MockRoom(name="Medicine Buddha Puja")
        room.event_id = uuid4()
        message = MockMessage(room=room, body="Please pray", message_type="PRAYER")
        mock_get_message.return_value = message
        mock_recipients.return_value = ([member], 1)
        mock_devices.return_value = {member: [MockDevice(user_id=member)]}

        result = get_chat_notification_targets(message_id=message.id)

        assert result.chat_kind == "EVENT"
        assert mock_recipients.call_args.kwargs["notification_type"] is None
        assert [recipient.user_id for recipient in result.recipients] == [member]

    @patch(
        "pecha_api.chat.notification_service._generate_presigned_url",
        return_value="https://example.com/group-avatar.png",
    )
    @patch(
        "pecha_api.chat.notification_service.get_group_avatar_key",
        return_value="groups/current-avatar.png",
    )
    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    @patch("pecha_api.chat.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.chat.notification_service.list_group_chat_recipient_user_ids")
    @patch("pecha_api.chat.notification_service.get_sender_short_name", return_value="Doe")
    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_group_message_carries_the_group_avatar(
        self,
        mock_session,
        mock_get_message,
        mock_sender_name,
        mock_recipients,
        mock_devices,
        _get_int,
        mock_avatar_key,
        mock_presign,
    ):
        """The group's current avatar, not the room image copied at creation."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        joiner = uuid4()
        group_id = uuid4()
        room = MockRoom(group_id=group_id, name="Sangha", img_url="groups/old-avatar.png")
        message = MockMessage(sender_id=uuid4(), room=room, body="Hello group")
        mock_get_message.return_value = message
        mock_recipients.return_value = ([joiner], 1)
        mock_devices.return_value = {joiner: [MockDevice(user_id=joiner)]}

        result = get_chat_notification_targets(message_id=message.id)

        assert result.message_type == "TEXT"
        assert result.title == "Doe"
        assert result.body == "Hello group"
        assert result.image_url == "https://example.com/group-avatar.png"
        assert mock_avatar_key.call_args.kwargs["group_id"] == group_id
        mock_presign.assert_called_once_with("groups/current-avatar.png")

    @patch(
        "pecha_api.chat.notification_service._generate_presigned_url",
        return_value="https://example.com/room.png",
    )
    @patch("pecha_api.chat.notification_service.get_group_avatar_key", return_value=None)
    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    @patch("pecha_api.chat.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.chat.notification_service.list_group_chat_recipient_user_ids")
    @patch("pecha_api.chat.notification_service.get_sender_short_name", return_value="Doe")
    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_group_without_an_avatar_falls_back_to_the_room_image(
        self,
        mock_session,
        mock_get_message,
        _sender_name,
        mock_recipients,
        mock_devices,
        _get_int,
        _avatar_key,
        mock_presign,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        joiner = uuid4()
        room = MockRoom(group_id=uuid4(), name="Sangha", img_url="groups/room.png")
        message = MockMessage(sender_id=uuid4(), room=room, body="Hello group")
        mock_get_message.return_value = message
        mock_recipients.return_value = ([joiner], 1)
        mock_devices.return_value = {joiner: [MockDevice(user_id=joiner)]}

        result = get_chat_notification_targets(message_id=message.id)

        assert result.image_url == "https://example.com/room.png"
        mock_presign.assert_called_once_with("groups/room.png")

    @patch("pecha_api.chat.notification_service._generate_presigned_url")
    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    @patch("pecha_api.chat.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.chat.notification_service.list_private_chat_recipient_user_ids")
    @patch("pecha_api.chat.notification_service.get_sender_display_name", return_value="Alice Doe")
    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_private_message_carries_no_image(
        self,
        mock_session,
        mock_get_message,
        mock_sender_name,
        mock_recipients,
        mock_devices,
        _get_int,
        mock_presign,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        peer_id = uuid4()
        room = MockRoom(sender_id=uuid4(), receiver_id=peer_id, name="DM")
        message = MockMessage(room=room, body="Hello")
        mock_get_message.return_value = message
        mock_recipients.return_value = [peer_id]
        mock_devices.return_value = {peer_id: [MockDevice(user_id=peer_id)]}

        result = get_chat_notification_targets(message_id=message.id)

        assert result.image_url is None
        mock_presign.assert_not_called()

    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room", return_value=None)
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_missing_message_raises_404(self, mock_session, _get_message):
        mock_session.return_value.__enter__.return_value = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            get_chat_notification_targets(message_id=uuid4())
        assert exc_info.value.status_code == 404


class TestPrayerNotificationCopy:

    def test_one_person_one_prayer(self):
        title, body = _build_prayer_notification_copy(
            room_name="Medicine Buddha Puja", people_count=1, prayer_total=1
        )

        assert title == "Someone prayed for you"
        assert body == "Medicine Buddha Puja"

    def test_one_person_many_prayers(self):
        title, _ = _build_prayer_notification_copy(
            room_name="Sangha", people_count=1, prayer_total=10
        )

        assert title == "Someone prayed for you 10 times"

    def test_many_people_many_prayers(self):
        title, _ = _build_prayer_notification_copy(
            room_name="Sangha", people_count=10, prayer_total=100
        )

        assert title == "Someone with 9 others prayed for you 100 times"

    def test_two_people_reads_one_other(self):
        title, _ = _build_prayer_notification_copy(
            room_name="Sangha", people_count=2, prayer_total=2
        )

        assert title == "Someone with 1 other prayed for you 2 times"


PRAYER_TARGETS = "pecha_api.chat.notification_service"


def _prayer_notification(message_id, people_count=10, prayer_total=100, latest_user_id=None):
    return SimpleNamespace(
        id=uuid4(),
        message_id=message_id,
        people_count=people_count,
        prayer_total=prayer_total,
        latest_user_id=latest_user_id or uuid4(),
    )


@patch(f"{PRAYER_TARGETS}.get_active_push_devices_by_user_ids")
@patch(f"{PRAYER_TARGETS}.filter_users_by_notification_preference")
@patch(f"{PRAYER_TARGETS}.count_message_prayers", return_value=12)
@patch(f"{PRAYER_TARGETS}.get_sender_display_name", return_value="Kunsang")
@patch(f"{PRAYER_TARGETS}._owning_group_id")
@patch(f"{PRAYER_TARGETS}.get_message_by_id_any_room")
@patch(f"{PRAYER_TARGETS}.get_prayer_notification_by_id")
@patch(f"{PRAYER_TARGETS}.SessionLocal")
class TestGetPrayerNotificationTargets:

    def _message(self, group_id):
        room = MockRoom(group_id=group_id, name="Sangha")
        room.event_id = None
        return MockMessage(room=room, message_type="PRAYER")

    def test_resolves_a_push_row_and_builds_its_summary_copy(
        self,
        mock_session,
        mock_get_notification,
        mock_get_message,
        mock_group,
        mock_name,
        _count,
        mock_filter,
        mock_devices,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        group_id = uuid4()
        message = self._message(group_id)
        notification = _prayer_notification(message.id)
        mock_get_notification.return_value = notification
        mock_get_message.return_value = message
        mock_group.return_value = group_id
        mock_filter.side_effect = lambda db, user_ids, notification_type, scope_id: user_ids
        device = MockDevice(user_id=message.sender_id)
        mock_devices.return_value = {message.sender_id: [device]}

        result = get_prayer_notification_targets(prayer_id=notification.id)

        assert mock_get_notification.call_args.kwargs["notification_id"] == notification.id
        assert result.prayer_id == notification.id
        assert result.requester_id == message.sender_id
        assert result.title == "Someone with 9 others prayed for you 100 times"
        # Never names who prayed, so never looks them up.
        mock_name.assert_not_called()
        assert result.body == "Sangha"
        assert result.image_url is None
        assert result.prayer_count == 12
        assert result.people_count == 10
        assert result.prayer_total == 100
        assert [r.user_id for r in result.recipients] == [message.sender_id]

    def test_honours_the_requesters_preference(
        self,
        mock_session,
        mock_get_notification,
        mock_get_message,
        mock_group,
        _name,
        _count,
        mock_filter,
        mock_devices,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        group_id = uuid4()
        message = self._message(group_id)
        mock_get_notification.return_value = _prayer_notification(message.id)
        mock_get_message.return_value = message
        mock_group.return_value = group_id
        mock_filter.return_value = []
        mock_devices.return_value = {}

        result = get_prayer_notification_targets(prayer_id=uuid4())

        from pecha_api.notification.notification_preference_enums import NotificationType

        assert mock_filter.call_args.kwargs["notification_type"] == NotificationType.PRAYER_RECEIVED
        assert mock_filter.call_args.kwargs["scope_id"] == group_id
        assert result.recipients == []
        assert result.total == 0

    def test_unknown_id_is_404(
        self,
        mock_session,
        mock_get_notification,
        mock_get_message,
        _group,
        _name,
        _count,
        _filter,
        _devices,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_notification.return_value = None

        with patch(f"{PRAYER_TARGETS}.get_prayer_by_id", return_value=None), \
                pytest.raises(HTTPException) as exc_info:
            get_prayer_notification_targets(prayer_id=uuid4())

        assert exc_info.value.status_code == 404
        mock_get_message.assert_not_called()

    def test_an_event_queued_before_deploy_still_resolves(
        self,
        mock_session,
        mock_get_notification,
        mock_get_message,
        mock_group,
        _name,
        _count,
        mock_filter,
        mock_devices,
    ):
        """Its prayer_id is a chat_message_prayers id: read as one person
        praying once."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        group_id = uuid4()
        message = self._message(group_id)
        mock_group.return_value = group_id
        mock_get_notification.return_value = None
        mock_get_message.return_value = message
        mock_filter.side_effect = lambda db, user_ids, notification_type, scope_id: user_ids
        mock_devices.return_value = {message.sender_id: [MockDevice(user_id=message.sender_id)]}
        legacy = SimpleNamespace(id=uuid4(), message_id=message.id, user_id=uuid4())

        with patch(f"{PRAYER_TARGETS}.get_prayer_by_id", return_value=legacy):
            result = get_prayer_notification_targets(prayer_id=legacy.id)

        assert mock_get_message.call_args.kwargs["message_id"] == message.id
        assert result.prayer_id == legacy.id
        assert result.title == "Someone prayed for you"
        assert result.people_count == 1
        assert result.prayer_total == 1
        assert [r.user_id for r in result.recipients] == [message.sender_id]

    def test_a_legacy_self_prayer_notifies_nobody(
        self,
        mock_session,
        mock_get_notification,
        mock_get_message,
        mock_group,
        _name,
        _count,
        mock_filter,
        mock_devices,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        group_id = uuid4()
        message = self._message(group_id)
        mock_group.return_value = group_id
        mock_get_notification.return_value = None
        mock_get_message.return_value = message
        mock_filter.side_effect = lambda db, user_ids, notification_type, scope_id: user_ids
        mock_devices.return_value = {}
        legacy = SimpleNamespace(id=uuid4(), message_id=message.id, user_id=message.sender_id)

        with patch(f"{PRAYER_TARGETS}.get_prayer_by_id", return_value=legacy):
            result = get_prayer_notification_targets(prayer_id=legacy.id)

        assert result.recipients == []
        assert result.total == 0

    def _event_room_message(self, room_img_url):
        room = MockRoom(group_id=None, name="Medicine Buddha Puja", img_url=room_img_url)
        room.event_id = uuid4()
        return MockMessage(room=room, message_type="PRAYER")

    def _resolve_for(self, message, mock_get_notification, mock_get_message, mock_group, mock_filter, mock_devices):
        mock_group.return_value = uuid4()
        mock_get_notification.return_value = _prayer_notification(message.id)
        mock_get_message.return_value = message
        mock_filter.side_effect = lambda db, user_ids, notification_type, scope_id: user_ids
        mock_devices.return_value = {}

    def test_an_event_room_carries_the_events_image_under_its_name(
        self,
        mock_session,
        mock_get_notification,
        mock_get_message,
        mock_group,
        _name,
        _count,
        mock_filter,
        mock_devices,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        message = self._event_room_message(room_img_url="rooms/stale.jpg")
        self._resolve_for(message, mock_get_notification, mock_get_message, mock_group, mock_filter, mock_devices)
        event = SimpleNamespace(image_url="events/puja.jpg")

        with patch(f"{PRAYER_TARGETS}.get_event_by_id", return_value=event) as mock_event, \
                patch(f"{PRAYER_TARGETS}._generate_presigned_url", side_effect=lambda key: f"signed:{key}"):
            result = get_prayer_notification_targets(prayer_id=uuid4())

        assert mock_event.call_args.args[1] == message.room.event_id
        assert result.image_url == "signed:events/puja.jpg"
        assert result.body == "Medicine Buddha Puja"
        assert result.event_id == message.room.event_id

    def test_an_event_without_an_image_falls_back_to_the_rooms(
        self,
        mock_session,
        mock_get_notification,
        mock_get_message,
        mock_group,
        _name,
        _count,
        mock_filter,
        mock_devices,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        message = self._event_room_message(room_img_url="rooms/puja.jpg")
        self._resolve_for(message, mock_get_notification, mock_get_message, mock_group, mock_filter, mock_devices)

        with patch(f"{PRAYER_TARGETS}.get_event_by_id", return_value=SimpleNamespace(image_url=None)), \
                patch(f"{PRAYER_TARGETS}._generate_presigned_url", side_effect=lambda key: f"signed:{key}"):
            result = get_prayer_notification_targets(prayer_id=uuid4())

        assert result.image_url == "signed:rooms/puja.jpg"

    def test_a_group_room_carries_the_rooms_image(
        self,
        mock_session,
        mock_get_notification,
        mock_get_message,
        mock_group,
        _name,
        _count,
        mock_filter,
        mock_devices,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        room = MockRoom(group_id=uuid4(), name="Sangha", img_url="groups/avatar.jpg")
        room.event_id = None
        message = MockMessage(room=room, message_type="PRAYER")
        self._resolve_for(message, mock_get_notification, mock_get_message, mock_group, mock_filter, mock_devices)

        with patch(f"{PRAYER_TARGETS}.get_event_by_id") as mock_event, \
                patch(f"{PRAYER_TARGETS}._generate_presigned_url", side_effect=lambda key: f"signed:{key}"):
            result = get_prayer_notification_targets(prayer_id=uuid4())

        mock_event.assert_not_called()
        assert result.image_url == "signed:groups/avatar.jpg"


class TestDeactivatePushDeviceService:
    @patch("pecha_api.chat.notification_service.deactivate_push_device_token_by_id")
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_deactivates_device(self, mock_session, mock_deactivate):
        mock_session.return_value.__enter__.return_value = MagicMock()
        device = MockDevice(user_id=uuid4())
        device.is_active = False
        mock_deactivate.return_value = device

        result = deactivate_push_device_service(push_device_id=device.id)

        assert result.push_device_id == device.id
        assert result.deactivated is True

    @patch("pecha_api.chat.notification_service.deactivate_push_device_token_by_id", return_value=None)
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_missing_device_raises_404(self, mock_session, _deactivate):
        mock_session.return_value.__enter__.return_value = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            deactivate_push_device_service(push_device_id=uuid4())
        assert exc_info.value.status_code == 404


class TestSenderShortName:
    @staticmethod
    def _db_returning(user):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = user
        return db

    def test_prefers_last_name(self):
        from pecha_api.chat.notification_repository import get_sender_short_name
        user = SimpleNamespace(lastname="Youdon", username="tyoudon")
        assert get_sender_short_name(self._db_returning(user), uuid4()) == "Youdon"

    def test_falls_back_to_username_without_last_name(self):
        from pecha_api.chat.notification_repository import get_sender_short_name
        user = SimpleNamespace(lastname="  ", username="tyoudon")
        assert get_sender_short_name(self._db_returning(user), uuid4()) == "tyoudon"

    def test_unknown_sender(self):
        from pecha_api.chat.notification_repository import get_sender_short_name
        assert get_sender_short_name(self._db_returning(None), uuid4()) == "Someone"


class TestPrayerNotificationQueue:
    @patch("pecha_api.chat.sqs_client.send_sqs_message", return_value="sqs-p")
    @patch(
        "pecha_api.chat.sqs_client.get",
        side_effect=lambda key: {
            "PRAYER_NOTIFICATION_SQS_QUEUE_URL": "https://sqs/prayer",
            "CHAT_NOTIFICATION_SQS_QUEUE_URL": "https://sqs/chat",
        }[key],
    )
    def test_prayer_pushes_go_to_the_prayer_queue(self, _get, mock_send):
        from pecha_api.chat.sqs_client import send_prayer_notification_message

        assert send_prayer_notification_message({"event_type": "PRAYER_RECEIVED"}) == "sqs-p"
        assert mock_send.call_args.args[0] == "https://sqs/prayer"

    @patch("pecha_api.chat.sqs_client.send_sqs_message", return_value="sqs-c")
    @patch(
        "pecha_api.chat.sqs_client.get",
        side_effect=lambda key: {
            "PRAYER_NOTIFICATION_SQS_QUEUE_URL": "",
            "CHAT_NOTIFICATION_SQS_QUEUE_URL": "https://sqs/chat",
        }[key],
    )
    def test_falls_back_to_the_chat_queue_when_unset(self, _get, mock_send):
        from pecha_api.chat.sqs_client import send_prayer_notification_message

        send_prayer_notification_message({"event_type": "PRAYER_RECEIVED"})
        assert mock_send.call_args.args[0] == "https://sqs/chat"

    @patch(
        "pecha_api.chat.sqs_client.get",
        side_effect=lambda key: {
            "PRAYER_NOTIFICATION_SQS_QUEUE_URL": "https://sqs/prayer",
            "CHAT_NOTIFICATION_SQS_QUEUE_URL": "",
        }[key],
    )
    def test_prayer_queue_alone_counts_as_configured(self, _get):
        from pecha_api.chat.sqs_client import (
            is_chat_notification_sqs_configured,
            is_prayer_notification_sqs_configured,
        )

        assert is_prayer_notification_sqs_configured()
        assert not is_chat_notification_sqs_configured()
