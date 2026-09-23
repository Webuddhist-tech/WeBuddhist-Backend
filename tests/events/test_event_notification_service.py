from datetime import datetime, timezone as tz
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

import pecha_api.app  # noqa: F401

from pecha_api.events.event_response_models import CreateEventRequest
from pecha_api.notification.notification_preference_enums import NotificationType
from pecha_api.events.event_service import create_event_service
from pecha_api.events.notification_dispatch_service import (
    enqueue_event_notification,
    reconcile_undispatched_event_notifications,
)
from pecha_api.events.notification_service import (
    _build_notification_copy,
    _get_event_name,
    _preview_body,
    get_event_notification_targets,
)
from pecha_api.events.notification_sqs_client import (
    EVENT_CREATED_EVENT,
    EVENT_NOTIFICATION_EVENT_VERSION,
    build_event_notification_event_body,
)


class MockUser:
    def __init__(self, user_id=None, email="author@example.com", firstname="Alice", lastname="Doe"):
        self.id = user_id or uuid4()
        self.email = email
        self.firstname = firstname
        self.lastname = lastname


class MockEvent:
    def __init__(self, event_id=None, group_id=None, created_by="author@example.com"):
        self.id = event_id or uuid4()
        self.group_id = group_id or uuid4()
        self.created_by = created_by
        self.created_at = datetime.now(tz.utc)
        self.notification_sqs_message_id = None
        self.notification_dispatched_at = None


class MockMetadataEntry:
    def __init__(self, name, language="EN"):
        self.name = name
        self.language = language


class MockDevice:
    def __init__(self, user_id, token="tok", platform="ANDROID"):
        self.id = uuid4()
        self.user_id = user_id
        self.token = token
        self.platform = platform


class TestPreviewAndCopy:
    def test_preview_truncates(self):
        assert _preview_body("hello world", 5) == "hell…"
        assert _preview_body("hi", 10) == "hi"

    @patch("pecha_api.events.notification_service.get_int", return_value=120)
    def test_copy_uses_event_name(self, _get_int):
        assert _build_notification_copy(event_name="Full Moon Meditation") == "Full Moon Meditation"

    @patch("pecha_api.events.notification_service.get_int", return_value=5)
    def test_copy_truncates_long_name(self, _get_int):
        assert _build_notification_copy(event_name="Full Moon Meditation") == "Full…"


class TestGetEventName:
    def test_prefers_english_entry(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            MockMetadataEntry("Tibetan name", language="BO"),
            MockMetadataEntry("English name", language="EN"),
        ]
        assert _get_event_name(db, uuid4()) == "English name"

    def test_falls_back_to_first_entry(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = [
            MockMetadataEntry("Only name", language="BO"),
        ]
        assert _get_event_name(db, uuid4()) == "Only name"

    def test_falls_back_when_no_entries(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.all.return_value = []
        assert _get_event_name(db, uuid4()) == "New event"


class TestBuildEventBody:
    def test_builds_versioned_event(self):
        event_id = str(uuid4())
        body = build_event_notification_event_body(event_id=event_id)
        assert body == {
            "event_type": EVENT_CREATED_EVENT,
            "version": EVENT_NOTIFICATION_EVENT_VERSION,
            "event_id": event_id,
        }


class TestEnqueueEventNotification:
    @patch("pecha_api.events.notification_dispatch_service.mark_event_notification_dispatched")
    @patch("pecha_api.events.notification_dispatch_service.send_event_notification_message")
    @patch("pecha_api.events.notification_dispatch_service.is_event_notification_sqs_configured", return_value=True)
    @patch("pecha_api.events.notification_dispatch_service.SessionLocal")
    def test_enqueues_and_marks_dispatched(self, mock_session, _configured, mock_send, mock_mark):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_send.return_value = "sqs-1"
        event_id = uuid4()

        result = enqueue_event_notification(event_id)

        assert result == "sqs-1"
        mock_send.assert_called_once()
        mock_mark.assert_called_once()

    @patch("pecha_api.events.notification_dispatch_service.is_event_notification_sqs_configured", return_value=False)
    def test_skips_when_unconfigured(self, _configured):
        assert enqueue_event_notification(uuid4()) is None

    @patch("pecha_api.events.notification_dispatch_service.send_event_notification_message", side_effect=RuntimeError("boom"))
    @patch("pecha_api.events.notification_dispatch_service.is_event_notification_sqs_configured", return_value=True)
    def test_returns_none_on_enqueue_failure(self, _configured, _send):
        assert enqueue_event_notification(uuid4()) is None


class TestReconcileUndispatched:
    @patch("pecha_api.events.notification_dispatch_service.enqueue_event_notification", return_value="sqs-1")
    @patch("pecha_api.events.notification_dispatch_service.list_undispatched_event_notifications")
    @patch("pecha_api.events.notification_dispatch_service.get_int", side_effect=lambda key: 60)
    @patch("pecha_api.events.notification_dispatch_service.is_event_notification_sqs_configured", return_value=True)
    @patch("pecha_api.events.notification_dispatch_service.SessionLocal")
    def test_requeues_undispatched_events(self, mock_session, _configured, _get_int, mock_list, mock_enqueue):
        mock_session.return_value.__enter__.return_value = MagicMock()
        event = MockEvent()
        mock_list.return_value = [event]

        assert reconcile_undispatched_event_notifications() == 1
        mock_enqueue.assert_called_once_with(event.id)


class TestGetEventNotificationTargets:
    @patch("pecha_api.events.notification_service.get_int", return_value=120)
    @patch("pecha_api.events.notification_service.get_active_push_devices_by_user_ids")
    @patch("pecha_api.events.notification_service.list_group_chat_recipient_user_ids")
    @patch("pecha_api.events.notification_service._get_event_name", return_value="Full Moon Meditation")
    @patch("pecha_api.events.notification_service.get_group_notification_title", return_value="Sangha")
    @patch("pecha_api.events.notification_service.get_user_by_email")
    @patch("pecha_api.events.notification_service.get_event_by_id")
    @patch("pecha_api.events.notification_service.SessionLocal")
    def test_targets_use_joiners_and_skip_users_without_devices(
        self, mock_session, mock_get_event, mock_get_user, mock_title, mock_name, mock_recipients, mock_devices, _get_int,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        author = MockUser()
        event = MockEvent(created_by=author.email, group_id=uuid4())
        mock_get_event.return_value = event
        mock_get_user.return_value = author

        joiner_with_device = uuid4()
        joiner_without_device = uuid4()
        mock_recipients.return_value = ([joiner_with_device, joiner_without_device], 2)
        device = MockDevice(user_id=joiner_with_device)
        mock_devices.return_value = {joiner_with_device: [device]}

        result = get_event_notification_targets(event_id=event.id, skip=0, limit=100)

        assert result.group_id == event.group_id
        assert result.author_id == author.id
        assert result.title == "Sangha"
        assert result.body == "Full Moon Meditation"
        assert len(result.recipients) == 1
        assert result.recipients[0].user_id == joiner_with_device
        assert result.total == 2
        assert result.has_more is False
        mock_recipients.assert_called_once_with(
            db=mock_session.return_value.__enter__.return_value,
            group_id=event.group_id,
            sender_id=author.id,
            skip=0,
            limit=100,
            notification_type=NotificationType.EVENT,
            # The audience is the whole group, but someone who muted this one
            # event should not hear about it anyway.
            event_id=event.id,
        )

    @patch("pecha_api.events.notification_service.get_event_by_id", return_value=None)
    @patch("pecha_api.events.notification_service.SessionLocal")
    def test_missing_event_raises_404(self, mock_session, _get_event):
        mock_session.return_value.__enter__.return_value = MagicMock()
        with pytest.raises(HTTPException) as exc_info:
            get_event_notification_targets(event_id=uuid4())
        assert exc_info.value.status_code == 404

    @patch("pecha_api.events.notification_service.get_user_by_email", return_value=None)
    @patch("pecha_api.events.notification_service.get_event_by_id")
    @patch("pecha_api.events.notification_service.SessionLocal")
    def test_missing_author_raises_404(self, mock_session, mock_get_event, _get_user):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_event.return_value = MockEvent()
        with pytest.raises(HTTPException) as exc_info:
            get_event_notification_targets(event_id=uuid4())
        assert exc_info.value.status_code == 404


class TestCreateEventEnqueuesNotification:
    def test_published_event_enqueues_notification(self):
        now = datetime.now(tz.utc)
        request = CreateEventRequest(
            group_id=uuid4(),
            start_date=now,
            end_date=now,
            metadata=[{"name": "Full Moon Meditation", "language": "EN"}],
        )
        author = SimpleNamespace(id=uuid4(), email="author@example.com")
        saved = SimpleNamespace(
            id=uuid4(),
            plan_id=None,
            accumulator_id=None,
            mantra_id=None,
            timer_id=None,
            group_recitation_collection_id=None,
            group_id=request.group_id,
            location_id=None,
            location=None,
            start_date=now,
            end_date=now,
            timezone=None,
            notifications_enabled=True,
            image_url=None,
            featured=False,
            event_format="hybrid",
            is_recurring=False,
            metadata_entries=[],
            links=[],
            created_at=now,
            created_by=author.email,
            updated_at=None,
        )

        with patch(
            "pecha_api.events.event_service.validate_cms_author_details",
            return_value=author,
        ), patch(
            "pecha_api.events.event_service.require_can_create_content",
        ), patch(
            "pecha_api.events.event_service.save_event",
            return_value=saved,
        ), patch(
            "pecha_api.events.event_service.enqueue_event_notification",
        ) as mock_enqueue:
            create_event_service(token="token", request=request)

        mock_enqueue.assert_called_once_with(saved.id)
