"""The rolling job that keeps recurring series topped up, and the sweep that
keeps their rows from growing without bound."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

from pecha_api.events.event_reminder_materialize_service import (
    materialize_recurring_event_reminders,
    purge_expired_event_reminders,
)

MODULE = "pecha_api.events.event_reminder_materialize_service"


def _ints(batch: int = 200, retention: int = 30):
    values = {
        "EVENT_REMINDER_MATERIALIZE_BATCH_SIZE": batch,
        "EVENT_REMINDER_RETENTION_DAYS": retention,
    }
    return lambda key: values[key]


def _event():
    return SimpleNamespace(id=uuid4())


class TestMaterializeRecurringEventReminders:
    @patch(f"{MODULE}.list_recurring_events_for_materialization")
    @patch(f"{MODULE}.recurring_reminders_enabled", return_value=False)
    def test_flag_off_does_not_even_read_the_table(self, _enabled, mock_list):
        assert materialize_recurring_event_reminders() == 0
        mock_list.assert_not_called()

    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.materialize_event_reminders", return_value=2)
    @patch(f"{MODULE}.list_recurring_events_for_materialization")
    @patch(f"{MODULE}.get_int", side_effect=_ints(batch=2))
    @patch(f"{MODULE}.recurring_reminders_enabled", return_value=True)
    def test_walks_every_page_in_keyset_order(
        self, _enabled, _get_int, mock_list, mock_materialize, mock_session
    ):
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        first_page = [_event(), _event()]
        mock_list.side_effect = [first_page, []]

        written = materialize_recurring_event_reminders()

        assert written == 4
        assert mock_materialize.call_count == 2
        # The second page resumes after the last id of the first.
        assert mock_list.call_args_list[1].kwargs["after_id"] == first_page[-1].id

    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.materialize_event_reminders", return_value=1)
    @patch(f"{MODULE}.list_recurring_events_for_materialization")
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.recurring_reminders_enabled", return_value=True)
    def test_commits_per_event(
        self, _enabled, _get_int, mock_list, _mock_materialize, mock_session
    ):
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        mock_list.side_effect = [[_event(), _event()], []]

        materialize_recurring_event_reminders()

        assert db.commit.call_count == 2

    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.materialize_event_reminders")
    @patch(f"{MODULE}.list_recurring_events_for_materialization")
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.recurring_reminders_enabled", return_value=True)
    def test_one_unexpandable_event_does_not_sink_the_sweep(
        self, _enabled, _get_int, mock_list, mock_materialize, mock_session
    ):
        """A rule that cannot be expanded - a lunar year with no calendar
        file, say - costs its own reminders and not everyone else's."""
        db = MagicMock()
        mock_session.return_value.__enter__.return_value = db
        mock_list.side_effect = [[_event(), _event()], []]
        mock_materialize.side_effect = [RuntimeError("no calendar for 2031"), 3]

        written = materialize_recurring_event_reminders()

        assert written == 3
        db.rollback.assert_called_once()
        assert db.commit.call_count == 1


class TestPurgeExpiredEventReminders:
    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.purge_reminders_before", return_value=7)
    @patch(f"{MODULE}.get_int", side_effect=_ints(retention=30))
    def test_cutoff_is_retention_days_back(self, _get_int, mock_purge, mock_session):
        mock_session.return_value.__enter__.return_value = MagicMock()

        assert purge_expired_event_reminders() == 7

        cutoff = mock_purge.call_args.kwargs["cutoff"]
        expected = datetime.now(timezone.utc) - timedelta(days=30)
        assert abs((cutoff - expected).total_seconds()) < 60

    @patch(f"{MODULE}.SessionLocal")
    @patch(f"{MODULE}.purge_reminders_before", return_value=0)
    @patch(f"{MODULE}.get_int", side_effect=_ints(retention=0))
    def test_retention_floors_at_one_day(self, _get_int, mock_purge, mock_session):
        """A zero-day retention would sweep reminders that are about to fire."""
        mock_session.return_value.__enter__.return_value = MagicMock()

        purge_expired_event_reminders()

        cutoff = mock_purge.call_args.kwargs["cutoff"]
        assert cutoff < datetime.now(timezone.utc) - timedelta(hours=23)
