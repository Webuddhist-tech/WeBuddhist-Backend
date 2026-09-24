"""Organizer-written notifications: what gets queued, and who receives it."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.events.event_announcement_service import (
    get_event_announcement_targets,
    send_event_announcement,
)
from pecha_api.events.notification_response_models import (
    EventAnnouncementAudience,
    SendEventAnnouncementRequest,
)
from pecha_api.notification.notification_preference_enums import NotificationType

MODULE = "pecha_api.events.event_announcement_service"


def _event(notifications_enabled: bool = True):
    return SimpleNamespace(
        id=uuid4(),
        group_id=uuid4(),
        created_by="author@example.com",
        notifications_enabled=notifications_enabled,
    )


def _request(audience=EventAnnouncementAudience.PARTICIPANTS):
    return SendEventAnnouncementRequest(
        title="Change of venue",
        body="We are in the main hall today.",
        audience=audience,
    )


class TestSendEventAnnouncement:
    @patch(f"{MODULE}.send_event_notification_message", return_value="sqs-1")
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=True)
    @patch("pecha_api.events.event_service._require_can_edit_event")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.validate_cms_author_details")
    def test_queues_one_announcement(
        self, _author, mock_session, mock_get_event, _perm, _configured, mock_send
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        event = _event()
        mock_get_event.return_value = event

        result = send_event_announcement(
            token="t", event_id=event.id, request=_request()
        )

        assert result.event_id == event.id
        assert result.sqs_message_id == "sqs-1"
        body = mock_send.call_args.args[0]
        assert body["event_type"] == "EVENT_ANNOUNCEMENT"
        assert body["title"] == "Change of venue"
        assert body["audience"] == "participants"
        # Each send is its own delivery, so the same words sent twice are two
        # announcements rather than one deduplicated away downstream.
        assert body["announcement_id"] == str(result.announcement_id)

    @patch(f"{MODULE}.send_event_notification_message")
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=True)
    @patch("pecha_api.events.event_service._require_can_edit_event")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.validate_cms_author_details")
    def test_rejects_when_the_event_switch_is_off(
        self, _author, mock_session, mock_get_event, _perm, _configured, mock_send
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_event.return_value = _event(notifications_enabled=False)

        with pytest.raises(HTTPException) as exc:
            send_event_announcement(
                token="t", event_id=uuid4(), request=_request()
            )

        assert exc.value.status_code == 409
        mock_send.assert_not_called()

    @patch("pecha_api.events.event_service._require_can_edit_event")
    @patch(f"{MODULE}.get_event_by_id", return_value=None)
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.validate_cms_author_details")
    def test_missing_event_is_404(self, _author, mock_session, _get_event, _perm):
        mock_session.return_value.__enter__.return_value = MagicMock()

        with pytest.raises(HTTPException) as exc:
            send_event_announcement(
                token="t", event_id=uuid4(), request=_request()
            )

        assert exc.value.status_code == 404

    @patch(f"{MODULE}.send_event_notification_message", side_effect=RuntimeError("down"))
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=True)
    @patch("pecha_api.events.event_service._require_can_edit_event")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.validate_cms_author_details")
    def test_queue_failure_surfaces_to_the_caller(
        self, _author, mock_session, mock_get_event, _perm, _configured, _mock_send
    ):
        """Unlike the automatic sends, somebody is watching this one happen -
        a silent failure would leave them believing it went out."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_event.return_value = _event()

        with pytest.raises(HTTPException) as exc:
            send_event_announcement(
                token="t", event_id=uuid4(), request=_request()
            )

        assert exc.value.status_code == 503

    def test_blank_copy_is_rejected_by_the_request_model(self):
        with pytest.raises(ValueError):
            SendEventAnnouncementRequest(title="   ", body="something")


class TestAnnouncementTargets:
    @patch(f"{MODULE}.get_active_push_devices_by_user_ids")
    @patch(f"{MODULE}.get_event_participants_paginated")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    def test_participants_audience_filters_on_the_event_type(
        self, mock_session, mock_get_event, mock_participants, mock_devices
    ):
        """EVENT, not EVENT_REMINDER: an announcement is something the event
        is saying, so silencing reminders must not silence it."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        event = _event()
        mock_get_event.return_value = event
        user = SimpleNamespace(id=uuid4())
        mock_participants.return_value = ([(user, None, None)], 1)
        mock_devices.return_value = {
            user.id: [SimpleNamespace(id=uuid4(), token="tok", platform="ANDROID")]
        }

        result = get_event_announcement_targets(
            event_id=event.id, audience=EventAnnouncementAudience.PARTICIPANTS
        )

        assert len(result.recipients) == 1
        assert (
            mock_participants.call_args.kwargs["notification_type"]
            == NotificationType.EVENT
        )

    @patch(f"{MODULE}.get_active_push_devices_by_user_ids", return_value={})
    @patch(f"{MODULE}.list_group_chat_recipient_user_ids", return_value=([], 0))
    @patch(f"{MODULE}.get_user_by_email")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    def test_group_audience_still_respects_a_mute_on_this_event(
        self, mock_session, mock_get_event, mock_user, mock_group_recipients, _devices
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        event = _event()
        mock_get_event.return_value = event
        mock_user.return_value = SimpleNamespace(id=uuid4())

        get_event_announcement_targets(
            event_id=event.id, audience=EventAnnouncementAudience.GROUP
        )

        assert mock_group_recipients.call_args.kwargs["event_id"] == event.id

    @patch(f"{MODULE}.get_event_participants_paginated")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    def test_switch_turned_off_after_queueing_suppresses_delivery(
        self, mock_session, mock_get_event, mock_participants
    ):
        """The organizer can flip the switch in the seconds between queueing
        an announcement and the worker picking it up."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_get_event.return_value = _event(notifications_enabled=False)

        result = get_event_announcement_targets(
            event_id=uuid4(), audience=EventAnnouncementAudience.PARTICIPANTS
        )

        assert result.recipients == []
        assert result.total == 0
        mock_participants.assert_not_called()

    @patch(f"{MODULE}.get_event_by_id", return_value=None)
    @patch(f"{MODULE}.SessionLocal")
    def test_missing_event_is_404(self, mock_session, _get_event):
        mock_session.return_value.__enter__.return_value = MagicMock()

        with pytest.raises(HTTPException) as exc:
            get_event_announcement_targets(
                event_id=uuid4(), audience=EventAnnouncementAudience.GROUP
            )

        assert exc.value.status_code == 404
