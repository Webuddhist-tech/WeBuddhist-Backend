"""The organizer's per-event switch, and the participant's per-event mute.

Two different controls that both stop a push: one belongs to whoever runs the
event, the other to each person receiving it.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.events.event_reminder_service import schedule_event_reminders
from pecha_api.notification.notification_preference_enums import (
    EVENT_SCOPED_TYPES,
    NotificationScope,
    NotificationType,
    V1_EVENT_TOGGLEABLE_TYPES,
)
from pecha_api.notification.notification_preference_response_models import (
    NotificationPreferenceUpdateDTO,
    UpdateNotificationPreferencesRequest,
)
from pecha_api.notification.notification_preference_service import (
    update_event_notification_preferences_service,
)

REMINDER_MODULE = "pecha_api.events.event_reminder_service"
PREF_MODULE = "pecha_api.notification.notification_preference_service"

UTC = timezone.utc


def _ints(key):
    return {
        "EVENT_REMINDER_MINUTES_BEFORE": 10,
        "EVENT_REMINDER_HORIZON_DAYS": 14,
    }[key]


def _flags(key):
    return {
        "EVENT_REMINDER_DAILY_ENABLED": "true",
        "EVENT_REMINDER_RECURRING_ENABLED": "true",
    }[key]


class TestOrganizerSwitchStopsReminders:
    @patch(f"{REMINDER_MODULE}.get", side_effect=_flags)
    @patch(f"{REMINDER_MODULE}.get_int", side_effect=_ints)
    @patch(f"{REMINDER_MODULE}.create_or_replace_reminder")
    def test_no_reminders_are_written_when_the_switch_is_off(
        self, mock_create, _ints_, _get
    ):
        event = SimpleNamespace(
            id=uuid4(),
            start_date=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
            end_date=datetime(2026, 10, 5, 17, 0, tzinfo=UTC),
            timezone="UTC",
            is_recurring=False,
            duration_days=1,
            notifications_enabled=False,
        )

        schedule_event_reminders(
            MagicMock(), event, now=datetime(2026, 9, 30, tzinfo=UTC)
        )

        mock_create.assert_not_called()

    @patch(f"{REMINDER_MODULE}.get", side_effect=_flags)
    @patch(f"{REMINDER_MODULE}.get_int", side_effect=_ints)
    @patch(f"{REMINDER_MODULE}.create_or_replace_reminder")
    def test_switch_on_writes_them_as_usual(self, mock_create, _ints_, _get):
        event = SimpleNamespace(
            id=uuid4(),
            start_date=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
            end_date=datetime(2026, 10, 1, 17, 0, tzinfo=UTC),
            timezone="UTC",
            is_recurring=False,
            duration_days=1,
            notifications_enabled=True,
        )

        schedule_event_reminders(
            MagicMock(), event, now=datetime(2026, 9, 30, tzinfo=UTC)
        )

        assert mock_create.call_count == 2


class TestPerEventMute:
    def test_both_of_an_event_s_notification_types_can_be_muted(self):
        """Muting one event has to cover what it announces as well as what it
        reminds about - otherwise "mute this event" leaves half of it on."""
        assert EVENT_SCOPED_TYPES == {
            NotificationType.EVENT,
            NotificationType.EVENT_REMINDER,
        }
        assert set(V1_EVENT_TOGGLEABLE_TYPES) == EVENT_SCOPED_TYPES

    @patch(f"{PREF_MODULE}.list_preferences_for_user", return_value=[])
    @patch(f"{PREF_MODULE}.upsert_preference")
    @patch(f"{PREF_MODULE}._assert_group_member")
    @patch(f"{PREF_MODULE}.get_event_by_id")
    @patch(f"{PREF_MODULE}.SessionLocal")
    @patch(f"{PREF_MODULE}.validate_and_extract_user_details")
    def test_mute_all_writes_an_event_scoped_row_per_type(
        self, mock_user, mock_session, mock_get_event, _member, mock_upsert, _rows
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        user_id = uuid4()
        mock_user.return_value = SimpleNamespace(id=user_id)
        event_id = uuid4()
        mock_get_event.return_value = SimpleNamespace(id=event_id, group_id=uuid4())

        update_event_notification_preferences_service(
            token="t",
            event_id=event_id,
            request=UpdateNotificationPreferencesRequest(
                preferences=[
                    NotificationPreferenceUpdateDTO(
                        notification_type="ALL", enabled=False
                    )
                ]
            ),
        )

        assert mock_upsert.call_count == len(V1_EVENT_TOGGLEABLE_TYPES)
        for call in mock_upsert.call_args_list:
            assert call.kwargs["scope_id"] == event_id
            assert call.kwargs["scope_type"] == NotificationScope.EVENT
            assert call.kwargs["enabled"] is False

    @patch(f"{PREF_MODULE}._assert_group_member")
    @patch(f"{PREF_MODULE}.get_event_by_id", return_value=None)
    @patch(f"{PREF_MODULE}.SessionLocal")
    @patch(f"{PREF_MODULE}.validate_and_extract_user_details")
    def test_unknown_event_is_404(
        self, mock_user, mock_session, _get_event, _member
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_user.return_value = SimpleNamespace(id=uuid4())

        with pytest.raises(HTTPException) as exc:
            update_event_notification_preferences_service(
                token="t",
                event_id=uuid4(),
                request=UpdateNotificationPreferencesRequest(
                    preferences=[
                        NotificationPreferenceUpdateDTO(
                            notification_type="ALL", enabled=False
                        )
                    ]
                ),
            )

        assert exc.value.status_code == 404

    @patch(f"{PREF_MODULE}.list_preferences_for_user", return_value=[])
    @patch(f"{PREF_MODULE}.upsert_preference")
    @patch(f"{PREF_MODULE}._assert_group_member")
    @patch(f"{PREF_MODULE}.get_event_by_id")
    @patch(f"{PREF_MODULE}.SessionLocal")
    @patch(f"{PREF_MODULE}.validate_and_extract_user_details")
    def test_a_type_the_event_cannot_send_is_rejected(
        self, mock_user, mock_session, mock_get_event, _member, _upsert, _rows
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_user.return_value = SimpleNamespace(id=uuid4())
        event_id = uuid4()
        mock_get_event.return_value = SimpleNamespace(id=event_id, group_id=uuid4())

        with pytest.raises(HTTPException) as exc:
            update_event_notification_preferences_service(
                token="t",
                event_id=event_id,
                request=UpdateNotificationPreferencesRequest(
                    preferences=[
                        NotificationPreferenceUpdateDTO(
                            notification_type="CHAT_MESSAGE", enabled=False
                        )
                    ]
                ),
            )

        assert exc.value.status_code == 422

    @patch(f"{PREF_MODULE}.list_preferences_for_user", return_value=[])
    @patch(f"{PREF_MODULE}.upsert_preference")
    @patch(f"{PREF_MODULE}._assert_group_member")
    @patch(f"{PREF_MODULE}.get_event_by_id")
    @patch(f"{PREF_MODULE}.SessionLocal")
    @patch(f"{PREF_MODULE}.validate_and_extract_user_details")
    def test_muting_until_a_date_is_accepted(
        self, mock_user, mock_session, mock_get_event, _member, mock_upsert, _rows
    ):
        """A snooze rather than a permanent mute - the column is already there
        for it, so "mute for a week" needs no extra storage."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_user.return_value = SimpleNamespace(id=uuid4())
        event_id = uuid4()
        mock_get_event.return_value = SimpleNamespace(id=event_id, group_id=uuid4())
        until = datetime.now(UTC) + timedelta(days=7)

        update_event_notification_preferences_service(
            token="t",
            event_id=event_id,
            request=UpdateNotificationPreferencesRequest(
                preferences=[
                    NotificationPreferenceUpdateDTO(
                        notification_type="EVENT_REMINDER", muted_until=until
                    )
                ]
            ),
        )

        assert mock_upsert.call_count == 1
        assert mock_upsert.call_args.kwargs["muted_until"] == until
