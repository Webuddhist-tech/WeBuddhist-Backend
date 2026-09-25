import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.repository import (
    SUPPRESSED_SQS_MESSAGE_ID,
    get_message_by_id_any_room,
    get_prayer_by_id,
    has_dispatched_prayer_since,
    last_dispatched_prayer_request_at,
    list_undispatched_chat_notification_messages,
    list_undispatched_prayer_notifications,
    mark_message_notification_dispatched,
    mark_prayer_notification_dispatched,
)
from pecha_api.chat.service import _message_type_value
from pecha_api.chat.sqs_client import (
    build_chat_notification_event_body,
    build_prayer_notification_event_body,
    is_chat_notification_sqs_configured,
    send_chat_notification_message,
)
from pecha_api.config import get_int
from pecha_api.db.database import SessionLocal

logger = logging.getLogger(__name__)


def _prayer_request_interval_allows_push(
    db,
    *,
    room_id: UUID,
    message_id: UUID,
) -> bool:
    """Whether this room may raise a prayer-request push now.

    A prayer request goes to every member of the room, so ten requests in a
    busy sangha is ten notifications for everybody. The first request in a
    quiet room sends immediately; the rest are held for the interval and
    travel as a count on the next push that does go out.
    """
    interval_seconds = max(get_int("PRAYER_REQUEST_NOTIFICATION_INTERVAL_SECONDS"), 0)
    if interval_seconds == 0:
        return True

    last_sent_at = last_dispatched_prayer_request_at(
        db=db,
        room_id=room_id,
        exclude_message_id=message_id,
    )
    if last_sent_at is None:
        return True
    return last_sent_at < datetime.now(timezone.utc) - timedelta(seconds=interval_seconds)


def _should_notify_prayer_request(message_id: UUID, room_id: UUID | None) -> bool:
    """Gate for a PRAYER message. Never raises: a failure here sends the push.

    Letting one extra notification through beats swallowing a prayer request
    because a read failed.
    """
    try:
        with SessionLocal() as db:
            if room_id is None:
                message = get_message_by_id_any_room(db=db, message_id=message_id)
                if message is None:
                    return False
                room_id = message.room_id
            return _prayer_request_interval_allows_push(
                db=db,
                room_id=room_id,
                message_id=message_id,
            )
    except Exception:
        logger.exception(
            "Failed to evaluate prayer request notification interval for %s", message_id
        )
        return True


def enqueue_chat_message_notification(
    message_id: UUID,
    *,
    message_type: str = ChatMessageType.TEXT.value,
    room_id: UUID | None = None,
) -> str | None:
    """Enqueue a chat message notification event. Never raises to callers.

    Returns the SQS MessageId on success, or None when the queue is not
    configured, a prayer request was held by the room's interval, or enqueue
    fails. The chat message itself is already persisted either way.

    `message_type` and `room_id` come from the caller, which already holds
    both, so an ordinary TEXT message costs no extra read to find out it is
    not a prayer request.
    """
    if not is_chat_notification_sqs_configured():
        logger.debug(
            "Skipping chat notification enqueue for %s; SQS queue not configured",
            message_id,
        )
        return None

    if message_type == ChatMessageType.PRAYER.value and not _should_notify_prayer_request(
        message_id=message_id, room_id=room_id
    ):
        try:
            with SessionLocal() as db:
                mark_message_notification_dispatched(
                    db=db,
                    message_id=message_id,
                    sqs_message_id=SUPPRESSED_SQS_MESSAGE_ID,
                )
        except Exception:
            logger.exception(
                "Failed to mark prayer request %s suppressed; it stays undispatched "
                "and reconcile will re-check it against the interval",
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
        # Read inside the session: a prayer request is re-checked against the
        # room's interval on retry, so a retry inside the window is held rather
        # than becoming a second push.
        pending = [
            (message.id, _message_type_value(message), message.room_id)
            for message in messages
        ]

    requeued = 0
    for message_id, message_type, room_id in pending:
        if enqueue_chat_message_notification(
            message_id, message_type=message_type, room_id=room_id
        ):
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
