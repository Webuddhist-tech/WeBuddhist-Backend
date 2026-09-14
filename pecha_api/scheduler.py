import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from pecha_api.chat.notification_dispatch_service import (
    reconcile_undispatched_chat_notifications,
    reconcile_undispatched_prayer_notifications,
)
from pecha_api.plans.groups.join_request_dispatch_service import (
    reconcile_undispatched_join_request_notifications,
)
from pecha_api.config import get_int
from pecha_api.events.notification_dispatch_service import (
    reconcile_undispatched_event_notifications,
)
from pecha_api.events.event_reminder_dispatch_service import (
    dispatch_due_event_reminders,
    reconcile_undispatched_event_reminders,
)
from pecha_api.group_posts.notification_dispatch_service import (
    reconcile_undispatched_group_post_notifications,
)
from pecha_api.plans.audio.audio_job_service import reconcile_undispatched_audio_jobs
from pecha_api.verse_of_day.verse_of_day_service import cleanup_expired_verses_of_day

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


def setup_scheduler() -> None:
    expiry_days = get_int("VERSE_OF_DAY_EXPIRY_DAYS")
    if expiry_days < 1:
        raise ValueError(
            f"VERSE_OF_DAY_EXPIRY_DAYS must be a positive integer, got {expiry_days}"
        )
    scheduler.add_job(
        cleanup_expired_verses_of_day,
        CronTrigger(hour=0, minute=0),
        args=[expiry_days],
        id="cleanup_expired_verses_of_day",
        name="Cleanup expired verses of the day",
        replace_existing=True,
    )

    reconcile_interval = max(get_int("AUDIO_JOB_DISPATCH_RECONCILE_INTERVAL_SECONDS"), 1)
    scheduler.add_job(
        reconcile_undispatched_audio_jobs,
        IntervalTrigger(seconds=reconcile_interval),
        id="reconcile_undispatched_audio_jobs",
        name="Fail undispatched pending audio jobs",
        replace_existing=True,
    )

    chat_reconcile_interval = max(
        get_int("CHAT_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS"),
        1,
    )
    scheduler.add_job(
        reconcile_undispatched_chat_notifications,
        IntervalTrigger(seconds=chat_reconcile_interval),
        id="reconcile_undispatched_chat_notifications",
        name="Re-enqueue undispatched chat notifications",
        replace_existing=True,
    )

    scheduler.add_job(
        reconcile_undispatched_prayer_notifications,
        IntervalTrigger(seconds=chat_reconcile_interval),
        id="reconcile_undispatched_prayer_notifications",
        name="Re-enqueue undispatched prayer notifications",
        replace_existing=True,
    )

    join_request_reconcile_interval = max(
        get_int("JOIN_REQUEST_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS"),
        1,
    )
    scheduler.add_job(
        reconcile_undispatched_join_request_notifications,
        IntervalTrigger(seconds=join_request_reconcile_interval),
        id="reconcile_undispatched_join_request_notifications",
        name="Re-enqueue undispatched join request notifications",
        replace_existing=True,
    )

    group_post_reconcile_interval = max(
        get_int("GROUP_POST_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS"),
        1,
    )
    scheduler.add_job(
        reconcile_undispatched_group_post_notifications,
        IntervalTrigger(seconds=group_post_reconcile_interval),
        id="reconcile_undispatched_group_post_notifications",
        name="Re-enqueue undispatched group post notifications",
        replace_existing=True,
    )

    event_reconcile_interval = max(
        get_int("EVENT_NOTIFICATION_DISPATCH_RECONCILE_INTERVAL_SECONDS"),
        1,
    )
    scheduler.add_job(
        reconcile_undispatched_event_notifications,
        IntervalTrigger(seconds=event_reconcile_interval),
        id="reconcile_undispatched_event_notifications",
        name="Re-enqueue undispatched event notifications",
        replace_existing=True,
    )

    event_reminder_dispatch_interval = max(
        get_int("EVENT_REMINDER_DISPATCH_INTERVAL_SECONDS"),
        1,
    )
    scheduler.add_job(
        dispatch_due_event_reminders,
        IntervalTrigger(seconds=event_reminder_dispatch_interval),
        id="dispatch_due_event_reminders",
        name="Dispatch due event reminders",
        replace_existing=True,
        max_instances=1,
    )

    event_reminder_reconcile_interval = max(
        get_int("EVENT_REMINDER_DISPATCH_RECONCILE_INTERVAL_SECONDS"),
        1,
    )
    scheduler.add_job(
        reconcile_undispatched_event_reminders,
        IntervalTrigger(seconds=event_reminder_reconcile_interval),
        id="reconcile_undispatched_event_reminders",
        name="Re-enqueue undispatched event reminders",
        replace_existing=True,
        max_instances=1,
    )

    if not scheduler.running:
        scheduler.start()
    logger.info(
        "Scheduler started: cleaning verses of the day older than %s day(s) daily at midnight; "
        "failing undispatched audio jobs every %s second(s); "
        "re-enqueueing undispatched chat notifications every %s second(s); "
        "re-enqueueing undispatched group post notifications every %s second(s); "
        "re-enqueueing undispatched event notifications every %s second(s); "
        "dispatching due event reminders every %s second(s)",
        expiry_days,
        reconcile_interval,
        chat_reconcile_interval,
        group_post_reconcile_interval,
        event_reconcile_interval,
        event_reminder_dispatch_interval,
    )


def shutdown_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down")
