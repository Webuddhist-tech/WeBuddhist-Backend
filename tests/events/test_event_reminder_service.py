from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from pecha_api.events.event_reminder_service import (
    REMINDER_TYPE_T_MINUS_10,
    REMINDER_TYPE_T_ZERO,
    clear_event_reminders,
    materialize_event_reminders,
    reschedule_event_reminders,
    schedule_event_reminders,
)

MODULE = "pecha_api.events.event_reminder_service"

UTC = timezone.utc


def _ints(minutes: int = 10, horizon: int = 14):
    values = {
        "EVENT_REMINDER_MINUTES_BEFORE": minutes,
        "EVENT_REMINDER_HORIZON_DAYS": horizon,
    }
    return lambda key: values[key]


def _flags(daily: bool = False, recurring: bool = False):
    values = {
        "EVENT_REMINDER_DAILY_ENABLED": "true" if daily else "false",
        "EVENT_REMINDER_RECURRING_ENABLED": "true" if recurring else "false",
    }
    return lambda key: values[key]


def _event(
    *,
    start_date: datetime,
    end_date: datetime,
    timezone_name: str = "UTC",
    is_recurring: bool = False,
    duration_days: int = 1,
):
    return SimpleNamespace(
        id=uuid4(),
        start_date=start_date,
        end_date=end_date,
        timezone=timezone_name,
        is_recurring=is_recurring,
        duration_days=duration_days,
    )


def _calls(mock_create):
    """(reminder_type, fire_at, occurrence_date, day_index, day_total) per write."""
    return [
        (
            call.args[2],
            call.args[3],
            call.args[4],
            call.kwargs.get("day_index"),
            call.kwargs.get("day_total"),
        )
        for call in mock_create.call_args_list
    ]


@patch(f"{MODULE}.get", side_effect=_flags())
@patch(f"{MODULE}.get_int", side_effect=_ints())
@patch(f"{MODULE}.create_or_replace_reminder")
class TestSingleDayEvent:
    def test_creates_both_reminders_for_a_future_event(self, mock_create, _ints_, _get):
        db = MagicMock()
        now = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
        start = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
        event = _event(start_date=start, end_date=start + timedelta(hours=8))

        schedule_event_reminders(db, event, now=now)

        assert _calls(mock_create) == [
            (REMINDER_TYPE_T_MINUS_10, start - timedelta(minutes=10), date(2026, 10, 2), None, None),
            (REMINDER_TYPE_T_ZERO, start, date(2026, 10, 2), None, None),
        ]
        db.commit.assert_not_called()

    def test_skips_reminders_whose_fire_time_already_passed(self, mock_create, _ints_, _get):
        now = datetime(2026, 10, 2, 9, 1, tzinfo=UTC)
        start = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
        event = _event(start_date=start, end_date=start + timedelta(hours=1))

        schedule_event_reminders(MagicMock(), event, now=now)

        mock_create.assert_not_called()

    def test_creates_only_t_zero_when_t_minus_already_passed(self, mock_create, _ints_, _get):
        # Five minutes out: the warning's fire time has gone, the start has not.
        now = datetime(2026, 10, 2, 8, 55, tzinfo=UTC)
        start = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
        event = _event(start_date=start, end_date=start + timedelta(hours=1))

        schedule_event_reminders(MagicMock(), event, now=now)

        assert [call[0] for call in _calls(mock_create)] == [REMINDER_TYPE_T_ZERO]

    def test_naive_timestamps_are_read_as_utc(self, mock_create, _ints_, _get):
        now = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
        start = datetime(2026, 10, 2, 9, 0)
        event = _event(start_date=start, end_date=datetime(2026, 10, 2, 17, 0))

        schedule_event_reminders(MagicMock(), event, now=now)

        assert len(_calls(mock_create)) == 2


class TestMinutesBefore:
    @patch(f"{MODULE}.get", side_effect=_flags())
    @patch(f"{MODULE}.get_int", side_effect=_ints(minutes=0))
    @patch(f"{MODULE}.create_or_replace_reminder")
    def test_floors_at_one_minute(self, mock_create, _ints_, _get):
        now = datetime(2026, 10, 1, 8, 0, tzinfo=UTC)
        start = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
        event = _event(start_date=start, end_date=start + timedelta(hours=1))

        schedule_event_reminders(MagicMock(), event, now=now)

        assert _calls(mock_create)[0][1] == start - timedelta(minutes=1)


class TestMultiDayEvent:
    @patch(f"{MODULE}.get", side_effect=_flags(daily=True))
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.create_or_replace_reminder")
    def test_one_pair_per_day_numbered(self, mock_create, _ints_, _get):
        now = datetime(2026, 9, 30, tzinfo=UTC)
        start = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
        end = datetime(2026, 10, 5, 17, 0, tzinfo=UTC)
        event = _event(start_date=start, end_date=end)

        schedule_event_reminders(MagicMock(), event, now=now)

        calls = _calls(mock_create)
        assert len(calls) == 10
        assert [call[2] for call in calls[::2]] == [
            date(2026, 10, day) for day in range(1, 6)
        ]
        assert calls[0][3:] == (1, 5)
        assert calls[-1][3:] == (5, 5)
        # Day three's warning is ten minutes before nine, not a day later.
        assert calls[4][1] == datetime(2026, 10, 3, 8, 50, tzinfo=UTC)

    @patch(f"{MODULE}.get", side_effect=_flags(daily=False))
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.create_or_replace_reminder")
    def test_flag_off_keeps_day_one_only(self, mock_create, _ints_, _get):
        now = datetime(2026, 9, 30, tzinfo=UTC)
        event = _event(
            start_date=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
            end_date=datetime(2026, 10, 5, 17, 0, tzinfo=UTC),
        )

        schedule_event_reminders(MagicMock(), event, now=now)

        calls = _calls(mock_create)
        assert len(calls) == 2
        assert all(call[2] == date(2026, 10, 1) for call in calls)
        assert all(call[3:] == (None, None) for call in calls)

    @patch(f"{MODULE}.get", side_effect=_flags(daily=True))
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.create_or_replace_reminder")
    def test_overnight_event_is_not_a_multi_day_event(self, mock_create, _ints_, _get):
        # 20:00 to 02:00 crosses midnight but is one evening: a second day of
        # reminders would fire 18 hours after everyone went home.
        now = datetime(2026, 9, 30, tzinfo=UTC)
        event = _event(
            start_date=datetime(2026, 10, 1, 20, 0, tzinfo=UTC),
            end_date=datetime(2026, 10, 2, 2, 0, tzinfo=UTC),
        )

        schedule_event_reminders(MagicMock(), event, now=now)

        calls = _calls(mock_create)
        assert len(calls) == 2
        assert all(call[2] == date(2026, 10, 1) for call in calls)

    @patch(f"{MODULE}.get", side_effect=_flags(daily=True))
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.create_or_replace_reminder")
    def test_local_wall_clock_survives_a_dst_shift(self, mock_create, _ints_, _get):
        # US DST begins 8 March 2026: 09:00 in New York is 14:00 UTC before it
        # and 13:00 UTC after, and attendees expect 09:00 on every day.
        tz = ZoneInfo("America/New_York")
        start = datetime(2026, 3, 6, 9, 0, tzinfo=tz).astimezone(UTC)
        end = datetime(2026, 3, 10, 17, 0, tzinfo=tz).astimezone(UTC)
        event = _event(start_date=start, end_date=end, timezone_name="America/New_York")

        schedule_event_reminders(MagicMock(), event, now=datetime(2026, 3, 1, tzinfo=UTC))

        starts = [call[1] for call in _calls(mock_create) if call[0] == REMINDER_TYPE_T_ZERO]
        assert [moment.astimezone(tz).hour for moment in starts] == [9, 9, 9, 9, 9]
        assert [moment.hour for moment in starts] == [14, 14, 13, 13, 13]

    @patch(f"{MODULE}.get", side_effect=_flags(daily=True))
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.create_or_replace_reminder")
    def test_unusable_timezone_falls_back_to_utc_without_raising(
        self, mock_create, _ints_, _get
    ):
        # Scheduling runs inside the event's own transaction, so a bad zone
        # must not take the event down with it.
        event = _event(
            start_date=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
            end_date=datetime(2026, 10, 3, 17, 0, tzinfo=UTC),
            timezone_name="Mars/Olympus_Mons",
        )

        schedule_event_reminders(MagicMock(), event, now=datetime(2026, 9, 30, tzinfo=UTC))

        calls = _calls(mock_create)
        assert [call[2] for call in calls[::2]] == [
            date(2026, 10, 1),
            date(2026, 10, 2),
            date(2026, 10, 3),
        ]

    @patch(f"{MODULE}.get", side_effect=_flags(daily=True))
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.create_or_replace_reminder")
    def test_missing_timezone_falls_back_to_utc(self, mock_create, _ints_, _get):
        event = _event(
            start_date=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
            end_date=datetime(2026, 10, 2, 17, 0, tzinfo=UTC),
            timezone_name=None,
        )

        schedule_event_reminders(MagicMock(), event, now=datetime(2026, 9, 30, tzinfo=UTC))

        assert [call[2] for call in _calls(mock_create)[::2]] == [
            date(2026, 10, 1),
            date(2026, 10, 2),
        ]


class TestRecurringEvent:
    @patch(f"{MODULE}.get", side_effect=_flags(recurring=False))
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.create_or_replace_reminder")
    def test_flag_off_writes_nothing(self, mock_create, _ints_, _get):
        event = _event(
            start_date=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
            end_date=datetime(2026, 10, 1, 17, 0, tzinfo=UTC),
            is_recurring=True,
        )

        schedule_event_reminders(MagicMock(), event, now=datetime(2026, 9, 30, tzinfo=UTC))

        mock_create.assert_not_called()

    @patch(f"{MODULE}.expand_occurrences")
    @patch(f"{MODULE}.get", side_effect=_flags(recurring=True))
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.create_or_replace_reminder")
    def test_warning_only_on_every_day_of_each_occurrence(
        self, mock_create, _ints_, _get, mock_expand
    ):
        mock_expand.return_value = [(date(2026, 10, 1), date(2026, 10, 3))]
        event = _event(
            start_date=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
            end_date=datetime(2026, 9, 3, 17, 0, tzinfo=UTC),
            is_recurring=True,
            duration_days=3,
        )

        schedule_event_reminders(MagicMock(), event, now=datetime(2026, 9, 30, tzinfo=UTC))

        calls = _calls(mock_create)
        # A series repeats forever with no per-occurrence way to decline, so
        # it sends the warning alone - no "Starting now" ten minutes later.
        assert {call[0] for call in calls} == {REMINDER_TYPE_T_MINUS_10}
        assert [call[2] for call in calls] == [
            date(2026, 10, 1),
            date(2026, 10, 2),
            date(2026, 10, 3),
        ]
        assert [call[3:] for call in calls] == [(1, 3), (2, 3), (3, 3)]
        assert calls[0][1] == datetime(2026, 10, 1, 8, 50, tzinfo=UTC)

    @patch(f"{MODULE}.expand_occurrences")
    @patch(f"{MODULE}.get", side_effect=_flags(recurring=True))
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.create_or_replace_reminder")
    def test_single_day_occurrence_is_not_numbered(
        self, mock_create, _ints_, _get, mock_expand
    ):
        mock_expand.return_value = [(date(2026, 10, 1), date(2026, 10, 1))]
        event = _event(
            start_date=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
            end_date=datetime(2026, 9, 1, 17, 0, tzinfo=UTC),
            is_recurring=True,
        )

        schedule_event_reminders(MagicMock(), event, now=datetime(2026, 9, 30, tzinfo=UTC))

        assert _calls(mock_create) == [
            (
                REMINDER_TYPE_T_MINUS_10,
                datetime(2026, 10, 1, 8, 50, tzinfo=UTC),
                date(2026, 10, 1),
                None,
                None,
            )
        ]

    @patch(f"{MODULE}.expand_occurrences")
    @patch(f"{MODULE}.get", side_effect=_flags(recurring=True))
    @patch(f"{MODULE}.get_int", side_effect=_ints(horizon=30))
    @patch(f"{MODULE}.create_or_replace_reminder")
    def test_expansion_is_bounded_by_the_horizon(
        self, _mock_create, _ints_, _get, mock_expand
    ):
        mock_expand.return_value = []
        event = _event(
            start_date=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
            end_date=datetime(2026, 9, 1, 17, 0, tzinfo=UTC),
            is_recurring=True,
        )

        schedule_event_reminders(MagicMock(), event, now=datetime(2026, 9, 30, 12, tzinfo=UTC))

        _event_arg, from_date, to_date = mock_expand.call_args.args
        assert from_date == date(2026, 9, 30)
        assert to_date == date(2026, 10, 30)


class TestRescheduleEventReminders:
    @patch(f"{MODULE}.get", side_effect=_flags())
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.create_or_replace_reminder")
    @patch(f"{MODULE}.clear_reminders_for_event")
    def test_clears_before_rewriting_in_the_same_session(
        self, mock_clear, mock_create, _ints_, _get
    ):
        db = MagicMock()
        event = _event(
            start_date=datetime(2026, 10, 2, 9, 0, tzinfo=UTC),
            end_date=datetime(2026, 10, 2, 17, 0, tzinfo=UTC),
        )

        order = []
        mock_clear.side_effect = lambda *a, **k: order.append("clear")
        mock_create.side_effect = lambda *a, **k: order.append("create")

        reschedule_event_reminders(db, event, now=datetime(2026, 10, 1, tzinfo=UTC))

        mock_clear.assert_called_once_with(db, event.id)
        assert order == ["clear", "create", "create"]
        db.commit.assert_not_called()


class TestClearEventReminders:
    @patch(f"{MODULE}.clear_reminders_for_event")
    def test_delegates_to_repository_without_committing(self, mock_clear):
        db = MagicMock()
        event_id = uuid4()

        clear_event_reminders(db, event_id)

        mock_clear.assert_called_once_with(db, event_id)
        db.commit.assert_not_called()


class TestMaterializeEventReminders:
    @patch(f"{MODULE}.get", side_effect=_flags(daily=True))
    @patch(f"{MODULE}.get_int", side_effect=_ints())
    @patch(f"{MODULE}.create_or_replace_reminder")
    @patch(f"{MODULE}.insert_reminder_if_missing")
    def test_adds_missing_days_without_touching_existing_rows(
        self, mock_insert, mock_replace, _ints_, _get
    ):
        # The rolling job re-walks days it has already written. Using the
        # replacing write here would clear dispatched_at on reminders already
        # delivered and send them a second time.
        event = _event(
            start_date=datetime(2026, 10, 1, 9, 0, tzinfo=UTC),
            end_date=datetime(2026, 10, 3, 17, 0, tzinfo=UTC),
        )

        written = materialize_event_reminders(
            MagicMock(), event, now=datetime(2026, 9, 30, tzinfo=UTC)
        )

        assert written == 6
        assert mock_insert.call_count == 6
        mock_replace.assert_not_called()
