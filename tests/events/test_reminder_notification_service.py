from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.events.event_reminder_service import REMINDER_TYPE_T_MINUS_10, REMINDER_TYPE_T_ZERO
from pecha_api.notification.notification_preference_enums import NotificationType
from pecha_api.events.reminder_notification_service import (
    _build_reminder_copy,
    _get_event_name,
    _reminder_superseded,
    get_event_reminder_targets,
)

MODULE = "pecha_api.events.reminder_notification_service"


class MockMetadataEntry:
    def __init__(self, name, language="EN"):
        self.name = name
        self.language = language


class MockEvent:
    def __init__(self, event_id=None):
        self.id = event_id or uuid4()


class MockUser:
    def __init__(self, user_id=None):
        self.id = user_id or uuid4()


class MockDevice:
    def __init__(self, user_id, token="tok", platform="ANDROID"):
        self.id = uuid4()
        self.user_id = user_id
        self.token = token
        self.platform = platform


def _reminder(fire_at=None, canceled_at=None):
    return SimpleNamespace(
        fire_at=fire_at or datetime.now(timezone.utc) - timedelta(seconds=5),
        canceled_at=canceled_at,
    )


class TestReminderSuperseded:
    @patch(f"{MODULE}.get_event_reminder")
    def test_false_when_fire_at_matches_and_not_canceled(self, mock_get):
        fire_at = datetime.now(timezone.utc) - timedelta(seconds=5)
        mock_get.return_value = _reminder(fire_at=fire_at)
        assert _reminder_superseded(MagicMock(), uuid4(), REMINDER_TYPE_T_ZERO, fire_at) is False

    @patch(f"{MODULE}.get_event_reminder")
    def test_true_when_canceled(self, mock_get):
        fire_at = datetime.now(timezone.utc)
        mock_get.return_value = _reminder(fire_at=fire_at, canceled_at=datetime.now(timezone.utc))
        assert _reminder_superseded(MagicMock(), uuid4(), REMINDER_TYPE_T_ZERO, fire_at) is True

    @patch(f"{MODULE}.get_event_reminder")
    def test_true_when_fire_at_moved_since_this_message_was_queued(self, mock_get):
        """A reschedule's upsert overwrites fire_at on the same row - the
        row itself can look perfectly valid (uncanceled, due) while no
        longer matching what this specific delivery attempt was queued
        for."""
        queued_for = datetime.now(timezone.utc) - timedelta(days=2)
        mock_get.return_value = _reminder(fire_at=datetime.now(timezone.utc) + timedelta(days=3))
        assert _reminder_superseded(MagicMock(), uuid4(), REMINDER_TYPE_T_ZERO, queued_for) is True

    @patch(f"{MODULE}.get_event_reminder", return_value=None)
    def test_true_when_row_no_longer_exists(self, _mock_get):
        assert _reminder_superseded(MagicMock(), uuid4(), REMINDER_TYPE_T_ZERO, datetime.now(timezone.utc)) is True

    @patch(f"{MODULE}.get_event_reminder")
    def test_true_when_fire_at_is_missing(self, mock_get):
        """Regression guard: a caller with no schedule identity at all (only
        possible for a message queued before fire_at existed) must not fall
        back to a weaker "not yet due" heuristic and accept whatever
        reminder happens to be due now - that reopens exactly the race this
        check exists to close."""
        mock_get.return_value = _reminder(fire_at=datetime.now(timezone.utc) - timedelta(seconds=5))
        assert _reminder_superseded(MagicMock(), uuid4(), REMINDER_TYPE_T_ZERO, None) is True

    @patch(f"{MODULE}.get_event_reminder")
    def test_false_when_fire_at_matches_the_claimed_value(self, mock_get):
        fire_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        mock_get.return_value = _reminder(fire_at=fire_at)
        assert _reminder_superseded(MagicMock(), uuid4(), REMINDER_TYPE_T_ZERO, fire_at) is False

    @patch(f"{MODULE}.get_event_reminder")
    def test_true_when_row_reclaimed_for_a_different_schedule_since_this_message_was_queued(
        self, mock_get,
    ):
        """Regression guard: a message that outlived a cancel + fresh
        dispatch of the same (event_id, reminder_type) row must not be
        delivered just because the row looks currently valid - it now
        belongs to a different, newer dispatch."""
        queued_for = datetime.now(timezone.utc) - timedelta(days=2)
        current_row = _reminder(fire_at=datetime.now(timezone.utc) - timedelta(seconds=5))
        mock_get.return_value = current_row

        assert _reminder_superseded(MagicMock(), uuid4(), REMINDER_TYPE_T_ZERO, queued_for) is True

    @patch(f"{MODULE}.get_event_reminder")
    def test_true_when_fire_at_differs_by_even_a_millisecond(self, mock_get):
        """The comparison is exact, not a tolerance window: fire_at
        round-trips losslessly through the SQS message and query param, so
        any mismatch - however small - means the row now belongs to a
        different schedule than the one this delivery attempt was queued
        for."""
        fire_at = datetime.now(timezone.utc)
        mock_get.return_value = _reminder(fire_at=fire_at + timedelta(milliseconds=1))
        assert _reminder_superseded(MagicMock(), uuid4(), REMINDER_TYPE_T_ZERO, fire_at) is True


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
        assert _get_event_name(db, uuid4()) == "Your event"


class TestBuildReminderCopy:
    def test_t_minus_10_includes_minutes(self):
        assert _build_reminder_copy(
            reminder_type=REMINDER_TYPE_T_MINUS_10, minutes_before=10,
        ) == "Starting in 10 minutes"

    def test_t_zero_says_starting_now(self):
        assert _build_reminder_copy(
            reminder_type=REMINDER_TYPE_T_ZERO, minutes_before=10,
        ) == "Starting now"

    def test_unknown_type_falls_back_to_starting_now(self):
        assert _build_reminder_copy(
            reminder_type="SOMETHING_ELSE", minutes_before=10,
        ) == "Starting now"


class TestGetEventReminderTargets:
    @patch(f"{MODULE}.get_event_by_id", return_value=None)
    @patch(f"{MODULE}.SessionLocal")
    def test_missing_event_raises_404(self, mock_session, _get_event):
        mock_session.return_value.__enter__.return_value = MagicMock()
        with pytest.raises(HTTPException) as exc:
            get_event_reminder_targets(event_id=uuid4(), reminder_type=REMINDER_TYPE_T_ZERO, minutes_before=10)
        assert exc.value.status_code == 404

    @patch(f"{MODULE}._reminder_superseded", return_value=False)
    @patch(f"{MODULE}.normalize_platform", side_effect=lambda p: p)
    @patch(f"{MODULE}.get_active_push_devices_by_user_ids")
    @patch(f"{MODULE}.get_event_participants_paginated")
    @patch(f"{MODULE}._get_event_name", return_value="Full Moon Meditation")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    def test_skips_recipients_without_devices_and_builds_body(
        self, mock_session, mock_get_event, _mock_name, mock_participants, mock_devices, _mock_platform, _superseded,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        event = MockEvent()
        mock_get_event.return_value = event

        with_device = MockUser()
        without_device = MockUser()
        mock_participants.return_value = ([(with_device, None), (without_device, None)], 2)
        device = MockDevice(user_id=with_device.id)
        mock_devices.return_value = {with_device.id: [device]}

        result = get_event_reminder_targets(
            event_id=event.id, reminder_type=REMINDER_TYPE_T_MINUS_10, minutes_before=10,
        )

        assert result.event_id == event.id
        assert result.title == "Full Moon Meditation"
        assert result.body == "Starting in 10 minutes"
        assert len(result.recipients) == 1
        assert result.recipients[0].user_id == with_device.id
        assert result.total == 2
        assert result.has_more is False

    @patch(f"{MODULE}._reminder_superseded", return_value=False)
    @patch(f"{MODULE}.get_active_push_devices_by_user_ids", return_value={})
    @patch(f"{MODULE}.get_event_participants_paginated", return_value=([], 0))
    @patch(f"{MODULE}._get_event_name", return_value="Event")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    def test_forwards_fire_at_to_the_superseded_check(
        self, mock_session, mock_get_event, _mock_name, _mock_participants, _mock_devices, mock_superseded,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        event = MockEvent()
        mock_get_event.return_value = event
        fire_at = datetime.now(timezone.utc)

        get_event_reminder_targets(
            event_id=event.id, reminder_type=REMINDER_TYPE_T_ZERO, minutes_before=10, fire_at=fire_at,
        )

        # Checked twice (fail-fast, then the authoritative recheck below) -
        # both calls must carry the same fire_at.
        mock_superseded.assert_called_with(
            mock_session.return_value.__enter__.return_value, event.id, REMINDER_TYPE_T_ZERO, fire_at,
        )
        assert mock_superseded.call_count == 2

    @patch(f"{MODULE}._reminder_superseded", return_value=False)
    @patch(f"{MODULE}.get_active_push_devices_by_user_ids", return_value={})
    @patch(f"{MODULE}.get_event_participants_paginated", return_value=([], 0))
    @patch(f"{MODULE}._get_event_name", return_value="Event")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    def test_participants_are_filtered_by_the_event_reminder_preference(
        self, mock_session, mock_get_event, _mock_name, mock_participants, _mock_devices, _superseded,
    ):
        """Regression guard: EVENT_REMINDER is a user-facing toggle, so the
        participant query has to resolve it - otherwise the API reports the
        reminder as off while it keeps being delivered. It must reach the
        query, not post-filter the page, so `total` matches the page."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        event = MockEvent()
        mock_get_event.return_value = event

        get_event_reminder_targets(
            event_id=event.id, reminder_type=REMINDER_TYPE_T_ZERO, minutes_before=10,
        )

        assert (
            mock_participants.call_args.kwargs["notification_type"]
            == NotificationType.EVENT_REMINDER
        )

    @patch(f"{MODULE}._reminder_superseded", return_value=False)
    @patch(f"{MODULE}.get_active_push_devices_by_user_ids", return_value={})
    @patch(f"{MODULE}.get_event_participants_paginated", return_value=([], 0))
    @patch(f"{MODULE}._get_event_name", return_value="Event")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    def test_clamps_out_of_range_pagination(
        self, mock_session, mock_get_event, _mock_name, mock_participants, _mock_devices, _superseded,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        event = MockEvent()
        mock_get_event.return_value = event

        result = get_event_reminder_targets(
            event_id=event.id,
            reminder_type=REMINDER_TYPE_T_ZERO,
            minutes_before=10,
            skip=-5,
            limit=10000,
        )

        assert result.skip == 0
        assert result.limit == 500
        assert mock_participants.call_args.kwargs["skip"] == 0
        assert mock_participants.call_args.kwargs["limit"] == 500

    @patch(f"{MODULE}._reminder_superseded", return_value=False)
    @patch(f"{MODULE}.get_active_push_devices_by_user_ids", return_value={})
    @patch(f"{MODULE}.get_event_participants_paginated", return_value=([], 0))
    @patch(f"{MODULE}._get_event_name", return_value="Event")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    def test_limit_below_one_floors_to_one(
        self, mock_session, mock_get_event, _mock_name, mock_participants, _mock_devices, _superseded,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        event = MockEvent()
        mock_get_event.return_value = event

        result = get_event_reminder_targets(
            event_id=event.id,
            reminder_type=REMINDER_TYPE_T_ZERO,
            minutes_before=10,
            limit=0,
        )

        assert result.limit == 1

    @patch(f"{MODULE}._reminder_superseded", return_value=True)
    @patch(f"{MODULE}.get_event_participants_paginated")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    def test_superseded_reminder_returns_no_recipients(
        self, mock_session, mock_get_event, mock_participants, _superseded,
    ):
        """Regression guard: this is the final gate closest to actual push
        delivery - a canceled or rescheduled reminder must not reach anyone,
        even if a stale SQS message already made it this far."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        event = MockEvent()
        mock_get_event.return_value = event

        result = get_event_reminder_targets(
            event_id=event.id, reminder_type=REMINDER_TYPE_T_MINUS_10, minutes_before=10,
        )

        assert result.recipients == []
        assert result.total == 0
        mock_participants.assert_not_called()

    @patch(f"{MODULE}._reminder_superseded")
    @patch(f"{MODULE}.get_active_push_devices_by_user_ids", return_value={})
    @patch(f"{MODULE}.get_event_participants_paginated", return_value=([], 0))
    @patch(f"{MODULE}._get_event_name", return_value="Event")
    @patch(f"{MODULE}.get_event_by_id")
    @patch(f"{MODULE}.SessionLocal")
    def test_authoritative_recheck_catches_a_change_during_participant_lookup(
        self, mock_session, mock_get_event, _mock_name, mock_participants, _mock_devices, mock_superseded,
    ):
        """Regression guard: a cancellation or reschedule landing while
        participant/device data is being resolved (which can take a while
        for large groups or multiple pages) must still be caught - not just
        one that happened before the fail-fast check ran."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        event = MockEvent()
        mock_get_event.return_value = event
        mock_superseded.side_effect = [False, True]

        result = get_event_reminder_targets(
            event_id=event.id, reminder_type=REMINDER_TYPE_T_ZERO, minutes_before=10,
        )

        assert result.recipients == []
        assert result.total == 0
        mock_participants.assert_called_once()
        assert mock_superseded.call_count == 2
