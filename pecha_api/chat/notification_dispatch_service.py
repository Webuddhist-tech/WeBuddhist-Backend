import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from pecha_api.chat.enums import ChatMessageType
from pecha_api.chat.repository import (
    SUPPRESSED_SQS_MESSAGE_ID,
    _as_utc,
    claim_prayer_notification_for_dispatch,
    claim_unreported_prayers,
    create_prayer_notification,
    get_last_prayer_notification,
    get_message_by_id_any_room,
    last_dispatched_prayer_request,
    last_prayer_request_push_to_user,
    list_due_prayer_notifications,
    list_undispatched_chat_notification_messages,
    list_undispatched_prayer_notifications,
    lock_prayer_request,
    mark_message_notification_dispatched,
    mark_prayer_notification_dispatched,
)
from pecha_api.chat.service import _message_type_value
from pecha_api.chat.sqs_client import (
    build_chat_notification_event_body,
    build_prayer_notification_event_body,
    is_chat_notification_sqs_configured,
    is_prayer_notification_sqs_configured,
    send_chat_notification_message,
    send_prayer_notification_message,
)
from pecha_api.config import get_int
from pecha_api.db.database import SessionLocal

logger = logging.getLogger(__name__)


def _prayer_request_interval_allows_push(
    db: Session,
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

    last_sent = last_dispatched_prayer_request(
        db=db,
        room_id=room_id,
        exclude_message_id=message_id,
    )
    if last_sent is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=interval_seconds)
    return last_sent.dispatched_at < cutoff


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
    is_prayer_request = message_type == ChatMessageType.PRAYER.value
    # Prayer requests only need the prayer queue, which may be set on its own.
    queue_configured = (
        is_prayer_notification_sqs_configured()
        if is_prayer_request
        else is_chat_notification_sqs_configured()
    )
    if not queue_configured:
        logger.debug(
            "Skipping chat notification enqueue for %s; SQS queue not configured",
            message_id,
        )
        return None

    if is_prayer_request and not _should_notify_prayer_request(
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

    # Prayer requests go to the prayer queue so their room-wide fan-out never
    # holds up ordinary chat pushes.
    send = (
        send_prayer_notification_message
        if is_prayer_request
        else send_chat_notification_message
    )
    try:
        sqs_message_id = send(
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
    if is_chat_notification_sqs_configured():
        message_type = None
    elif is_prayer_notification_sqs_configured():
        # Only the prayer queue is set: retry just prayer requests, so TEXT
        # messages that can never be sent don't fill every batch.
        message_type = ChatMessageType.PRAYER.value
    else:
        return 0

    grace_seconds = max(get_int("CHAT_NOTIFICATION_DISPATCH_RECONCILE_GRACE_SECONDS"), 1)
    batch_size = max(get_int("CHAT_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE"), 1)
    older_than = datetime.now(timezone.utc) - timedelta(seconds=grace_seconds)

    with SessionLocal() as db:
        messages = list_undispatched_chat_notification_messages(
            db=db,
            older_than=older_than,
            limit=batch_size,
            message_type=message_type,
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


def _prayer_interval_is_open(last_created_at, interval_seconds: int) -> bool:
    if interval_seconds == 0 or last_created_at is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=interval_seconds)
    return _as_utc(last_created_at) <= cutoff


def _create_prayer_notification_if_due(message_id: UUID, prayer_user_id: UUID) -> UUID | None:
    """Decide whether this request's requester gets a push now and, if so,
    record it. Returns the new notification id, or None when no push is due.

    The request row is locked for the whole decision, so two pray calls landing
    together cannot both find the interval open. Prayers that arrive while the
    interval is closed are not lost: they stay unreported on their count rows
    and the next push claims them. Claiming the counts and recording the push
    commit together, so a push never reports prayers another push also did.
    """
    interval_seconds = max(get_int("PRAYER_REQUEST_NOTIFICATION_INTERVAL_SECONDS"), 0)
    with SessionLocal() as db:
        message = lock_prayer_request(db=db, message_id=message_id)
        if message is None or message.sender_id == prayer_user_id:
            return None

        previous = get_last_prayer_notification(db=db, message_id=message_id)
        if not _prayer_interval_is_open(
            previous.created_at if previous else None, interval_seconds
        ):
            return None

        # The requester's own prayers are claimed too, so they never pile up,
        # but they are neither counted nor named.
        claimed = [
            row
            for row in claim_unreported_prayers(db=db, message_id=message_id)
            if row.user_id != message.sender_id
        ]
        if not claimed:
            # Nothing is committed, so any claim rolls back with the session.
            return None

        latest = max(claimed, key=lambda row: row.last_prayed_at)
        notification = create_prayer_notification(
            db=db,
            message_id=message_id,
            people_count=len(claimed),
            prayer_total=sum(row.count for row in claimed),
            latest_user_id=latest.user_id,
        )
        return notification.id


def _send_prayer_notification(notification_id: UUID) -> str | None:
    """Send one recorded prayer push to SQS and record its MessageId.

    A send failure leaves the row without an SQS id for reconcile to retry."""
    try:
        sqs_message_id = send_prayer_notification_message(
            build_prayer_notification_event_body(prayer_id=str(notification_id))
        )
    except Exception:
        logger.exception(
            "Failed to enqueue prayer notification %s", notification_id
        )
        return None

    try:
        with SessionLocal() as db:
            mark_prayer_notification_dispatched(
                db=db,
                notification_id=notification_id,
                sqs_message_id=sqs_message_id,
            )
    except Exception:
        logger.exception(
            "Enqueued prayer notification %s but failed to persist SQS MessageId %s",
            notification_id,
            sqs_message_id,
        )
    return sqs_message_id


def _claim_and_send_prayer_notification(notification_id: UUID) -> str | None:
    """Claim one recorded prayer push and send it. None when another replica
    claimed it first, or the claim failed and the row waits for the next poll."""
    try:
        with SessionLocal() as db:
            if not claim_prayer_notification_for_dispatch(
                db=db, notification_id=notification_id
            ):
                return None
    except Exception:
        logger.exception("Failed to claim prayer notification %s", notification_id)
        return None
    return _send_prayer_notification(notification_id)


def _prayer_notification_gap_seconds() -> int:
    return max(get_int("PRAYER_NOTIFICATION_GAP_SECONDS"), 0)


def notify_prayers_for_request(message_id: UUID, prayer_user_id: UUID) -> str | None:
    """Run the prayer-received gate for one request after someone prayed.
    Never raises to callers.

    At most one push per request per interval, and none for the requester's
    own prayers. With PRAYER_NOTIFICATION_GAP_SECONDS set the push is only
    recorded here and dispatch_due_prayer_notifications sends it, so it cannot
    land on top of a prayer-request push. Returns the SQS MessageId when a push
    was sent now, otherwise None. The prayers themselves are already persisted
    either way.
    """
    if not is_prayer_notification_sqs_configured():
        logger.debug(
            "Skipping prayer notification for %s; SQS queue not configured",
            message_id,
        )
        return None

    try:
        notification_id = _create_prayer_notification_if_due(
            message_id=message_id, prayer_user_id=prayer_user_id
        )
    except Exception:
        logger.exception("Failed to evaluate prayer notification for %s", message_id)
        return None
    if notification_id is None:
        return None
    if _prayer_notification_gap_seconds() > 0:
        return None

    return _claim_and_send_prayer_notification(notification_id)


def _clear_of_prayer_request_pushes(
    *,
    requester_id: UUID,
    created_at: datetime,
    now: datetime,
    gap_seconds: int,
) -> bool:
    """Whether a prayer-received push to `requester_id` can go out now without
    landing beside a prayer-request push they were sent in the last gap.

    Never raises: a failed read sends the push rather than holding it."""
    max_hold_seconds = max(get_int("PRAYER_NOTIFICATION_MAX_HOLD_SECONDS"), gap_seconds)
    if now - _as_utc(created_at) >= timedelta(seconds=max_hold_seconds):
        return True
    try:
        with SessionLocal() as db:
            last_request_push = last_prayer_request_push_to_user(
                db=db,
                user_id=requester_id,
                since=now - timedelta(seconds=gap_seconds),
            )
    except Exception:
        logger.exception(
            "Failed to check recent prayer-request pushes for %s", requester_id
        )
        return True
    return last_request_push is None


def dispatch_due_prayer_notifications() -> int:
    """Send the prayer-received pushes that are clear of prayer-request pushes.

    The two prayer pushes must not arrive together. Someone often prays for a
    request and then posts their own straight after, which would hand the first
    requester "someone prayed for you" and "X is requesting a prayer" at once.
    So a prayer-received push waits PRAYER_NOTIFICATION_GAP_SECONDS after it was
    recorded - long enough for that follow-up request to go out first - and then
    until the requester has had no prayer-request push for that long either.
    The prayer-request push goes to a whole room and is never the one delayed.
    PRAYER_NOTIFICATION_MAX_HOLD_SECONDS caps the wait for someone whose rooms
    are busy enough to keep it closed.
    """
    if not is_prayer_notification_sqs_configured():
        return 0

    gap_seconds = _prayer_notification_gap_seconds()
    batch_size = max(get_int("CHAT_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE"), 1)
    now = datetime.now(timezone.utc)

    with SessionLocal() as db:
        due = list_due_prayer_notifications(
            db=db,
            created_before=now - timedelta(seconds=gap_seconds),
            limit=batch_size,
        )

    sent = 0
    for notification in due:
        if gap_seconds and not _clear_of_prayer_request_pushes(
            requester_id=notification.requester_id,
            created_at=notification.created_at,
            now=now,
            gap_seconds=gap_seconds,
        ):
            continue
        if _claim_and_send_prayer_notification(notification.id):
            sent += 1
    return sent


def reconcile_undispatched_prayer_notifications() -> int:
    """Re-send prayer pushes that were claimed but never got an SQS MessageId.

    Covers the same commit-before-send crash window as chat messages. Neither
    the gate nor the gap is re-run: the row is the push that was already
    decided, and it was clear of prayer-request pushes when it was claimed.
    """
    if not is_prayer_notification_sqs_configured():
        return 0

    grace_seconds = max(get_int("CHAT_NOTIFICATION_DISPATCH_RECONCILE_GRACE_SECONDS"), 1)
    batch_size = max(get_int("CHAT_NOTIFICATION_DISPATCH_RECONCILE_BATCH_SIZE"), 1)
    older_than = datetime.now(timezone.utc) - timedelta(seconds=grace_seconds)

    with SessionLocal() as db:
        notifications = list_undispatched_prayer_notifications(
            db=db,
            older_than=older_than,
            limit=batch_size,
        )
        notification_ids = [notification.id for notification in notifications]

    requeued = 0
    for notification_id in notification_ids:
        if _send_prayer_notification(notification_id):
            requeued += 1
            logger.info("Re-enqueued undispatched prayer notification %s", notification_id)

    return requeued
