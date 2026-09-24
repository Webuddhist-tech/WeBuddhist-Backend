import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pecha_api.chat.repository import (
    SUPPRESSED_SQS_MESSAGE_ID,
    get_message_by_id_any_room,
    get_prayer_by_id,
    has_dispatched_prayer_since,
    list_undispatched_chat_notification_messages,
    list_undispatched_prayer_notifications,
    mark_message_notification_dispatched,
    mark_prayer_notification_dispatched,
)
from pecha_api.chat.sqs_client import (
    build_chat_notification_event_body,
    build_prayer_notification_event_body,
    is_chat_notification_sqs_configured,
    send_chat_notification_message,
)
from pecha_api.config import get_int
from pecha_api.db.database import SessionLocal

logger = logging.getLogger(__name__)


def enqueue_chat_message_notification(message_id: UUID) -> str | None:
    """Enqueue a chat message notification event. Never raises to callers.

    Returns the SQS MessageId on success, or None when the queue is not
    configured or enqueue fails. The chat message itself is already persisted.
    """
    if not is_chat_notification_sqs_configured():
        logger.debug(
            "Skipping chat notification enqueue for %s; SQS queue not configured",
            message_id,
        )
        return None

    try:
        sqs_message_id = send_chat_notification_message(
            build_chat_notification_event_body(message_id=str(message_id))
        )
    except Exception:
        logger.exception("Failed to enqueue chat notification for message %s", message_id)
        return None

    try:
        with SessionLocal() as db:
            mark_message_notification_dispatched(
                db=db,
                message_id=message_id,
                sqs_message_id=sqs_message_id,
            )
    except Exception:
        logger.exception(
            "Enqueued chat notification for %s but failed to persist SQS MessageId %s",
            message_id,
            sqs_message_id,
        )
    return sqs_message_id


def reconcile_undispatched_chat_notifications() -> int:
    """Re-enqueue chat messages that never recorded an SQS MessageId.

    Covers the commit-before-send crash window. Worker-side per-device
    idempotency makes duplicate queue events safe.
    """
    if not is_chat_notification_sqs_configured():
        return 0

    grace_seconds = max(get_int("CHAT_NOTIFICATION_DISPATCH_RECONCILE_GRACE_SECONDS"), 1)
    batch_size = max(get_int("CHAT_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE"), 1)
    older_than = datetime.now(timezone.utc) - timedelta(seconds=grace_seconds)

    with SessionLocal() as db:
        messages = list_undispatched_chat_notification_messages(
            db=db,
            older_than=older_than,
            limit=batch_size,
        )
        message_ids = [message.id for message in messages]

    requeued = 0
    for message_id in message_ids:
        if enqueue_chat_message_notification(message_id):
            requeued += 1
            logger.info("Re-enqueued undispatched chat notification for %s", message_id)

    return requeued


def _should_notify_prayer(db, prayer) -> bool:
    """Whether this prayer earns its own push.

    Two reasons it does not: the requester prayed for their own request, or
    another prayer for the same request already raised one inside the coalesce
    window - twelve people praying in quick succession is one notification
    saying twelve are praying, not twelve notifications.
    """
    message = get_message_by_id_any_room(db=db, message_id=prayer.message_id)
    if message is None or message.sender_id == prayer.user_id:
        return False

    coalesce_seconds = max(get_int("PRAYER_NOTIFICATION_COALESCE_SECONDS"), 0)
    if coalesce_seconds == 0:
        return True
    since = datetime.now(timezone.utc) - timedelta(seconds=coalesce_seconds)
    return not has_dispatched_prayer_since(
        db=db,
        message_id=prayer.message_id,
        since=since,
        exclude_prayer_id=prayer.id,
    )


def enqueue_prayer_notification(prayer_id: UUID) -> str | None:
    """Enqueue a prayer notification event. Never raises to callers.

    Returns the SQS MessageId on success, or None when the queue is not
    configured, the prayer does not earn a push, or enqueue fails. The prayer
    itself is already persisted.
    """
    if not is_chat_notification_sqs_configured():
        logger.debug(
            "Skipping prayer notification enqueue for %s; SQS queue not configured",
            prayer_id,
        )
        return None

    try:
        with SessionLocal() as db:
            prayer = get_prayer_by_id(db=db, prayer_id=prayer_id)
            if prayer is None:
                return None
            if not _should_notify_prayer(db=db, prayer=prayer):
                mark_prayer_notification_dispatched(
                    db=db,
                    prayer_id=prayer_id,
                    sqs_message_id=SUPPRESSED_SQS_MESSAGE_ID,
                )
                return None
    except Exception:
        logger.exception("Failed to evaluate prayer notification for %s", prayer_id)
        return None

    try:
        sqs_message_id = send_chat_notification_message(
            build_prayer_notification_event_body(prayer_id=str(prayer_id))
        )
    except Exception:
        logger.exception("Failed to enqueue prayer notification for prayer %s", prayer_id)
        return None

    try:
        with SessionLocal() as db:
            mark_prayer_notification_dispatched(
                db=db,
                prayer_id=prayer_id,
                sqs_message_id=sqs_message_id,
            )
    except Exception:
        logger.exception(
            "Enqueued prayer notification for %s but failed to persist SQS MessageId %s",
            prayer_id,
            sqs_message_id,
        )
    return sqs_message_id


def reconcile_undispatched_prayer_notifications() -> int:
    """Re-enqueue prayers that never recorded an SQS MessageId.

    Covers the same commit-before-send crash window as chat messages.
    """
    if not is_chat_notification_sqs_configured():
        return 0

    grace_seconds = max(get_int("CHAT_NOTIFICATION_DISPATCH_RECONCILE_GRACE_SECONDS"), 1)
    batch_size = max(get_int("CHAT_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE"), 1)
    older_than = datetime.now(timezone.utc) - timedelta(seconds=grace_seconds)

    with SessionLocal() as db:
        prayers = list_undispatched_prayer_notifications(
            db=db,
            older_than=older_than,
            limit=batch_size,
        )
        prayer_ids = [prayer.id for prayer in prayers]

    requeued = 0
    for prayer_id in prayer_ids:
        if enqueue_prayer_notification(prayer_id):
            requeued += 1
            logger.info("Re-enqueued undispatched prayer notification for %s", prayer_id)

    return requeued
