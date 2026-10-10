from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.events.event_reminder_dispatch_service import (
    _reminder_still_due,
    _send_reminder,
    dispatch_due_event_reminders,
    reconcile_undispatched_event_reminders,
)

MODULE = "pecha_api.events.event_reminder_dispatch_service"


def _reminder(fire_at=None, canceled_at=None):
    return SimpleNamespace(
        id=uuid4(),
        event_id=uuid4(),
        reminder_type="T_MINUS_10",
        fire_at=fire_at or datetime.now(timezone.utc),
        canceled_at=canceled_at,
    )


class TestReminderStillDue:
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.get_reminder_by_id")
    def test_true_when_unchanged_and_not_canceled(self, mock_get, mock_session):
        mock_session.return_value.__enter__.return_value = MagicMock()
        reminder = _reminder()
        mock_get.return_value = reminder

        assert _reminder_still_due(reminder.id, reminder.fire_at) is True

    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.get_reminder_by_id")
    def test_false_when_canceled_concurrently(self, mock_get, mock_session):
        mock_session.return_value.__enter__.return_value = MagicMock()
        reminder = _reminder(canceled_at=datetime.now(timezone.utc))
        mock_get.return_value = reminder

        assert _reminder_still_due(reminder.id, reminder.fire_at) is False

    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.get_reminder_by_id")
    def test_false_when_fire_at_was_superseded_by_reschedule(self, mock_get, mock_session):
        mock_session.return_value.__enter__.return_value = MagicMock()
        original_fire_at = datetime.now(timezone.utc)
        reminder = _reminder(fire_at=original_fire_at + timedelta(days=3))
        mock_get.return_value = reminder

        assert _reminder_still_due(reminder.id, original_fire_at) is False

    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.get_reminder_by_id", return_value=None)
    def test_false_when_row_no_longer_exists(self, _mock_get, mock_session):
        mock_session.return_value.__enter__.return_value = MagicMock()

        assert _reminder_still_due(uuid4(), datetime.now(timezone.utc)) is False


class TestSendReminder:
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.mark_reminder_sqs_message_id")
    @patch(f"{MODULE}.build_event_reminder_event_body")
    @patch(f"{MODULE}.send_event_notification_message", return_value="sqs-1")
    def test_sends_and_marks_dispatched(self, mock_send, mock_build, mock_mark, mock_session):
        mock_session.return_value.__enter__.return_value = MagicMock()
        fire_at = datetime.now(timezone.utc)
        event_id = uuid4()

        result = _send_reminder(uuid4(), event_id, "T_MINUS_10", fire_at)

        assert result == "sqs-1"
        mock_build.assert_called_once_with(
            event_id=str(event_id), reminder_type="T_MINUS_10", fire_at=fire_at.isoformat(),
        )
        mock_send.assert_called_once()
        mock_mark.assert_called_once()

    @patch(f"{MODULE}.send_event_notification_message", side_effect=RuntimeError("boom"))
    def test_returns_none_when_send_fails(self, _mock_send):
        assert _send_reminder(uuid4(), uuid4(), "T_ZERO", datetime.now(timezone.utc)) is None

    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.mark_reminder_sqs_message_id", side_effect=RuntimeError("db down"))
    @patch(f"{MODULE}.send_event_notification_message", return_value="sqs-2")
    def test_still_returns_message_id_when_marking_fails(self, _mock_send, _mock_mark, mock_session):
        mock_session.return_value.__enter__.return_value = MagicMock()

        assert _send_reminder(uuid4(), uuid4(), "T_ZERO", datetime.now(timezone.utc)) == "sqs-2"


class TestDispatchDueEventReminders:
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=False)
    def test_skips_when_sqs_not_configured(self, _configured):
        assert dispatch_due_event_reminders() == 0

    @patch(f"{MODULE}.get_int", return_value=50)
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=True)
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.list_due_reminders")
    @patch(f"{MODULE}.claim_reminder_for_dispatch", return_value=True)
    @patch(f"{MODULE}._reminder_still_due", return_value=True)
    @patch(f"{MODULE}._send_reminder", return_value="sqs-1")
    def test_dispatches_a_claimed_and_still_due_reminder(
        self, mock_send, _still_due, _claim, mock_list, mock_session, _configured, _get_int,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        reminder = _reminder()
        mock_list.return_value = [reminder]

        assert dispatch_due_event_reminders() == 1
        mock_send.assert_called_once_with(
            reminder.id, reminder.event_id, reminder.reminder_type, reminder.fire_at,
        )

    @patch(f"{MODULE}.get_int", return_value=50)
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=True)
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.list_due_reminders")
    @patch(f"{MODULE}.claim_reminder_for_dispatch", return_value=False)
    @patch(f"{MODULE}._send_reminder")
    def test_skips_reminder_another_poller_already_claimed(
        self, mock_send, _claim, mock_list, mock_session, _configured, _get_int,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_list.return_value = [_reminder()]

        assert dispatch_due_event_reminders() == 0
        mock_send.assert_not_called()

    @patch(f"{MODULE}.get_int", return_value=50)
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=True)
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.list_due_reminders")
    @patch(f"{MODULE}.claim_reminder_for_dispatch", return_value=True)
    @patch(f"{MODULE}._reminder_still_due", return_value=False)
    @patch(f"{MODULE}._send_reminder")
    def test_skips_claimed_reminder_superseded_by_concurrent_event_update(
        self, mock_send, _still_due, _claim, mock_list, mock_session, _configured, _get_int,
    ):
        """Regression guard: this is the race where an event cancellation or
        reschedule commits its reminder change after the claim - the claim
        must not result in a stale send."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_list.return_value = [_reminder()]

        assert dispatch_due_event_reminders() == 0
        mock_send.assert_not_called()


    @patch(f"{MODULE}.get_int", return_value=300)
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=True)
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.list_due_reminders", return_value=[])
    def test_only_lists_reminders_within_the_lateness_window(
        self, mock_list, mock_session, _configured, _get_int,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()

        dispatch_due_event_reminders()

        kwargs = mock_list.call_args.kwargs
        assert kwargs["now"] - kwargs["not_before"] == timedelta(seconds=300)

class TestReconcileUndispatchedEventReminders:
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=False)
    def test_skips_when_sqs_not_configured(self, _configured):
        assert reconcile_undispatched_event_reminders() == 0

    @patch(f"{MODULE}.get_int", return_value=60)
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=True)
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.list_undispatched_reminders_missing_sqs_id")
    @patch(f"{MODULE}._reminder_still_due", return_value=True)
    @patch(f"{MODULE}._send_reminder", return_value="sqs-3")
    def test_requeues_a_stuck_reminder_still_due(
        self, mock_send, _still_due, mock_list, mock_session, _configured, _get_int,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        reminder = _reminder()
        mock_list.return_value = [reminder]

        assert reconcile_undispatched_event_reminders() == 1
        mock_send.assert_called_once_with(
            reminder.id, reminder.event_id, reminder.reminder_type, reminder.fire_at,
        )

    @patch(f"{MODULE}.get_int", return_value=60)
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=True)
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.list_undispatched_reminders_missing_sqs_id")
    @patch(f"{MODULE}._reminder_still_due", return_value=False)
    @patch(f"{MODULE}._send_reminder")
    def test_skips_a_stuck_reminder_superseded_by_concurrent_event_update(
        self, mock_send, _still_due, mock_list, mock_session, _configured, _get_int,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_list.return_value = [_reminder()]

        assert reconcile_undispatched_event_reminders() == 0
        mock_send.assert_not_called()

    @patch(f"{MODULE}.get_int", return_value=300)
    @patch(f"{MODULE}.is_event_notification_sqs_configured", return_value=True)
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.list_undispatched_reminders_missing_sqs_id", return_value=[])
    def test_only_lists_stuck_reminders_within_the_lateness_window(
        self, mock_list, mock_session, _configured, _get_int,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        before = datetime.now(timezone.utc)

        reconcile_undispatched_event_reminders()

        not_before = mock_list.call_args.kwargs["not_before"]
        after = datetime.now(timezone.utc)
        assert before - timedelta(seconds=300) <= not_before <= after - timedelta(seconds=300)
