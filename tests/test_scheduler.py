from unittest.mock import MagicMock, patch

import pytest

from pecha_api.scheduler import setup_scheduler, shutdown_scheduler


def _get_int_side_effect(key: str) -> int:
    defaults = {
        "VERSE_OF_DAY_EXPIRY_DAYS": 7,
        "AUDIO_JOB_DISPATCH_RECONCILE_INTERVAL_SECONDS": 60,
        "AUDIO_JOB_DISPATCH_RECONCILE_GRACE_SECONDS": 120,
        "AUDIO_JOB_DISPATCH_RECONCILE_BATCH_SIZE": 50,
        "CHAT_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS": 30,
        "JOIN_REQUEST_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS": 60,
        "GROUP_POST_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS": 45,
        "EVENT_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS": 90,
        "EVENT_REMINDER_DISPATCH_INTERVAL_SECONDS": 60,
        "EVENT_REMINDER_DISPATCH_RECONCILE_INTERVAL_SECONDS": 60,
    }
    return defaults[key]


def test_setup_scheduler_rejects_non_positive_retention():
    with patch("pecha_api.scheduler.get_int", return_value=0), patch(
        "pecha_api.scheduler.scheduler"
    ) as mock_scheduler:
        mock_scheduler.running = False

        with pytest.raises(ValueError, match="positive integer"):
            setup_scheduler()

        mock_scheduler.add_job.assert_not_called()
        mock_scheduler.start.assert_not_called()


def test_setup_scheduler_rejects_negative_retention():
    with patch("pecha_api.scheduler.get_int", return_value=-7), patch(
        "pecha_api.scheduler.scheduler"
    ) as mock_scheduler:
        mock_scheduler.running = False

        with pytest.raises(ValueError, match="positive integer"):
            setup_scheduler()

        mock_scheduler.add_job.assert_not_called()


def test_setup_scheduler_registers_cleanup_and_reconcile_jobs():
    with patch("pecha_api.scheduler.get_int", side_effect=_get_int_side_effect), patch(
        "pecha_api.scheduler.scheduler"
    ) as mock_scheduler, patch(
        "pecha_api.scheduler.CronTrigger"
    ) as mock_cron_trigger, patch(
        "pecha_api.scheduler.IntervalTrigger"
    ) as mock_interval_trigger:
        mock_scheduler.running = False
        mock_cron_trigger.return_value = MagicMock()
        mock_interval_trigger.return_value = MagicMock()

        setup_scheduler()

        assert mock_scheduler.add_job.call_count == 9
        job_ids = [call.kwargs["id"] for call in mock_scheduler.add_job.call_args_list]
        assert job_ids == [
            "cleanup_expired_verses_of_day",
            "reconcile_undispatched_audio_jobs",
            "reconcile_undispatched_chat_notifications",
            "reconcile_undispatched_prayer_notifications",
            "reconcile_undispatched_join_request_notifications",
            "reconcile_undispatched_group_post_notifications",
            "reconcile_undispatched_event_notifications",
            "dispatch_due_event_reminders",
            "reconcile_undispatched_event_reminders",
        ]
        assert mock_scheduler.add_job.call_args_list[0].kwargs["args"] == [7]
        assert [call.kwargs for call in mock_interval_trigger.call_args_list] == [
            {"seconds": 60},
            {"seconds": 30},
            # Prayer notifications reconcile on the chat interval.
            {"seconds": 30},
            {"seconds": 60},
            {"seconds": 45},
            {"seconds": 90},
            {"seconds": 60},
            {"seconds": 60},
        ]
        mock_scheduler.start.assert_called_once()


def test_shutdown_scheduler_when_running():
    with patch("pecha_api.scheduler.scheduler") as mock_scheduler:
        mock_scheduler.running = True

        shutdown_scheduler()

        mock_scheduler.shutdown.assert_called_once_with(wait=False)


def test_shutdown_scheduler_when_not_running():
    with patch("pecha_api.scheduler.scheduler") as mock_scheduler:
        mock_scheduler.running = False

        shutdown_scheduler()

        mock_scheduler.shutdown.assert_not_called()
