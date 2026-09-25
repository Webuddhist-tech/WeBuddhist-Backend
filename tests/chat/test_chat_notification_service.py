import json
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
    _count_held_prayer_requests,
    _preview_body,
    deactivate_push_device_service,
    get_chat_notification_targets,
)
from pecha_api.chat.sqs_client import (
    CHAT_MESSAGE_CREATED_EVENT,
    CHAT_NOTIFICATION_EVENT_VERSION,
    build_chat_notification_event_body,
)


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
            chat_kind="PRIVATE",
            room_name="Alice & Bob",
            sender_name="Alice Doe",
            message_body="Hello there",
        )
        assert title == "Alice Doe"
        assert body == "Hello there"

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_group_copy_uses_room_and_sender_preview(self, _get_int):
        title, body = _build_notification_copy(
            chat_kind="GROUP",
            room_name="Sangha",
            sender_name="Alice Doe",
            message_body="Hello group",
        )
        assert title == "Sangha"
        assert body == "Alice Doe: Hello group"

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_prayer_copy_names_the_requester_and_drops_the_room(self, _get_int):
        """With the room's image attached, the name is redundant."""
        title, body = _build_notification_copy(
            chat_kind="EVENT",
            room_name="Dzongsar Drolma Bumtshok",
            sender_name="Tenzin Youdon",
            message_body="For my niece Sarah, that her treatment is swift.",
            message_type="PRAYER",
            has_image=True,
        )
        assert title == "Tenzin Youdon is requesting a prayer 🙏"
        assert body == "For my niece Sarah, that her treatment is swift."
        assert "Dzongsar" not in title and "Dzongsar" not in body

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_prayer_without_an_image_keeps_the_room_name(self, _get_int):
        """Nothing else would say which sangha the prayer came from."""
        title, body = _build_notification_copy(
            chat_kind="EVENT",
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
            chat_kind="GROUP",
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
            chat_kind="GROUP",
            room_name="Sangha",
            sender_name="Alice Doe",
            message_body="A prayer request far longer than the preview allows",
            message_type="PRAYER",
            has_image=False,
        )
        assert body.startswith("Sangha: ")
        assert len(body.removeprefix("Sangha: ")) == 20


class TestCountHeldPrayerRequests:
    @patch("pecha_api.chat.notification_service.count_suppressed_prayer_requests", return_value=2)
    @patch("pecha_api.chat.notification_service.last_dispatched_prayer_request_at")
    def test_counts_from_the_previous_sent_push(self, mock_last_sent, mock_count):
        sent_at = datetime(2026, 9, 25, 10, 0, tzinfo=timezone.utc)
        mock_last_sent.return_value = sent_at
        room_id, message_id = uuid4(), uuid4()

        assert _count_held_prayer_requests(
            db=MagicMock(), room_id=room_id, message_id=message_id
        ) == 2
        assert mock_count.call_args.kwargs["since"] == sent_at

    @patch("pecha_api.chat.notification_service.count_suppressed_prayer_requests", return_value=1)
    @patch("pecha_api.chat.notification_service.last_dispatched_prayer_request_at", return_value=None)
    def test_a_room_that_never_pushed_counts_everything_held(self, _last_sent, mock_count):
        assert _count_held_prayer_requests(
            db=MagicMock(), room_id=uuid4(), message_id=uuid4()
        ) == 1
        assert mock_count.call_args.kwargs["since"] is None

    @patch("pecha_api.chat.notification_service.count_suppressed_prayer_requests", return_value=0)
    @patch("pecha_api.chat.notification_service.last_dispatched_prayer_request_at", return_value=None)
    def test_both_queries_exclude_the_message_being_sent(self, mock_last_sent, mock_count):
        """Without this the "last sent push" would be this very message, since
        the backend stamps it before the worker asks for targets, and the count
        would always come out zero."""
        message_id = uuid4()

        _count_held_prayer_requests(db=MagicMock(), room_id=uuid4(), message_id=message_id)

        assert mock_last_sent.call_args.kwargs["exclude_message_id"] == message_id
        assert mock_count.call_args.kwargs["exclude_message_id"] == message_id


class TestHeldPrayerRequestCopy:
    """What the interval skipped, as words on the end of the body. The held
    requests are not listed - the room shows each one in full."""

    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    def test_no_suffix_when_nothing_was_held(self, _get_int):
        _, body = _build_notification_copy(
            chat_kind="GROUP",
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
            chat_kind="GROUP",
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
            chat_kind="GROUP",
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
            chat_kind="GROUP",
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
            chat_kind="GROUP",
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
            chat_kind="GROUP",
            room_name="Sangha",
            sender_name="Alice Doe",
            message_body="Hello group",
            held_count=5,
        )
        assert body == "Alice Doe: Hello group"


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


class TestPrayerRequestNotificationInterval:
    """A prayer request goes to every member of the room, so ten requests in a
    busy sangha is ten notifications for everybody. One push per room per
    interval; the rest are held and travel as a count on the next one."""

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_chat_notification_message", return_value="sqs-1")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request_at", return_value=None)
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=1140)
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=True)
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
    @patch("pecha_api.chat.notification_dispatch_service.send_chat_notification_message")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request_at")
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=1140)
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_request_inside_the_interval_is_held(
        self, mock_session, _configured, _get_int, mock_last_sent, mock_send, mock_mark
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_last_sent.return_value = datetime.now(timezone.utc) - timedelta(minutes=4)

        result = enqueue_chat_message_notification(
            uuid4(), message_type="PRAYER", room_id=uuid4()
        )

        assert result is None
        mock_send.assert_not_called()
        # Marked, not left undispatched: reconcile only retries rows that never
        # recorded an SQS id, so a held request stays held.
        assert mock_mark.call_args.kwargs["sqs_message_id"] == SUPPRESSED_SQS_MESSAGE_ID

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_chat_notification_message", return_value="sqs-2")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request_at")
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=1140)
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_request_after_the_interval_sends(
        self, mock_session, _configured, _get_int, mock_last_sent, mock_send, _mark
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_last_sent.return_value = datetime.now(timezone.utc) - timedelta(minutes=20)

        result = enqueue_chat_message_notification(
            uuid4(), message_type="PRAYER", room_id=uuid4()
        )

        assert result == "sqs-2"
        mock_send.assert_called_once()

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_chat_notification_message", return_value="sqs-3")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request_at")
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=0)
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_zero_disables_the_interval(
        self, mock_session, _configured, _get_int, mock_last_sent, mock_send, _mark
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_last_sent.return_value = datetime.now(timezone.utc)

        result = enqueue_chat_message_notification(
            uuid4(), message_type="PRAYER", room_id=uuid4()
        )

        assert result == "sqs-3"
        mock_send.assert_called_once()
        mock_last_sent.assert_not_called()

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_chat_notification_message", return_value="sqs-4")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request_at")
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=True)
    @patch("pecha_api.chat.notification_dispatch_service.SessionLocal")
    def test_ordinary_chat_is_never_gated(
        self, mock_session, _configured, mock_last_sent, mock_send, _mark
    ):
        """A TEXT message costs no extra read to find out it is not a prayer."""
        mock_session.return_value.__enter__.return_value = MagicMock()

        result = enqueue_chat_message_notification(uuid4(), message_type="TEXT")

        assert result == "sqs-4"
        mock_last_sent.assert_not_called()

    @patch("pecha_api.chat.notification_dispatch_service.mark_message_notification_dispatched")
    @patch("pecha_api.chat.notification_dispatch_service.send_chat_notification_message", return_value="sqs-5")
    @patch(
        "pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request_at",
        side_effect=RuntimeError("boom"),
    )
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=1140)
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=True)
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
    @patch("pecha_api.chat.notification_dispatch_service.send_chat_notification_message", return_value="sqs-6")
    @patch("pecha_api.chat.notification_dispatch_service.last_dispatched_prayer_request_at", return_value=None)
    @patch("pecha_api.chat.notification_dispatch_service.get_int", return_value=1140)
    @patch("pecha_api.chat.notification_dispatch_service.is_chat_notification_sqs_configured", return_value=True)
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
        mock_session.return_value.__enter__.return_value = MagicMock()
        sender_id = uuid4()
        peer_id = uuid4()
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
    @patch("pecha_api.chat.notification_service.list_group_chat_recipient_user_ids")
    @patch("pecha_api.chat.notification_service.get_sender_display_name", return_value="Alice Doe")
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
        assert result.title == "Sangha"
        assert result.body == "Alice Doe: Hello group"
        assert len(result.recipients) == 1
        assert result.recipients[0].user_id == joiner_with_device
        assert result.total == 2
        assert result.has_more is False

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

    @patch("pecha_api.chat.notification_service._generate_presigned_url")
    @patch("pecha_api.chat.notification_service.get_int", return_value=120)
    @patch("pecha_api.chat.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.chat.notification_service.list_group_chat_recipient_user_ids")
    @patch("pecha_api.chat.notification_service.get_sender_display_name", return_value="Alice Doe")
    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room")
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_ordinary_message_carries_no_image(
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
        joiner = uuid4()
        room = MockRoom(group_id=uuid4(), name="Sangha", img_url="groups/avatar.png")
        message = MockMessage(sender_id=uuid4(), room=room, body="Hello group")
        mock_get_message.return_value = message
        mock_recipients.return_value = ([joiner], 1)
        mock_devices.return_value = {joiner: [MockDevice(user_id=joiner)]}

        result = get_chat_notification_targets(message_id=message.id)

        assert result.message_type == "TEXT"
        assert result.image_url is None
        assert result.title == "Sangha"
        mock_presign.assert_not_called()

    @patch("pecha_api.chat.notification_service.get_message_by_id_any_room", return_value=None)
    @patch("pecha_api.chat.notification_service.SessionLocal")
    def test_missing_message_raises_404(self, mock_session, _get_message):
        mock_session.return_value.__enter__.return_value = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            get_chat_notification_targets(message_id=uuid4())
        assert exc_info.value.status_code == 404


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
