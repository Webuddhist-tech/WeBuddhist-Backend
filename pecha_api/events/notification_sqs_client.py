from typing import Any, Dict

from fastapi import HTTPException

from pecha_api.config import get
from pecha_api.shared.sqs_client import send_sqs_message

EVENT_CREATED_EVENT = "EVENT_CREATED"
EVENT_REMINDER_EVENT = "EVENT_REMINDER"
EVENT_ANNOUNCEMENT_EVENT = "EVENT_ANNOUNCEMENT"
EVENT_NOTIFICATION_EVENT_VERSION = 1


def get_event_notification_sqs_queue_url() -> str:
    return get("EVENT_NOTIFICATION_SQS_QUEUE_URL").strip()


def is_event_notification_sqs_configured() -> bool:
    return bool(get_event_notification_sqs_queue_url())


def build_event_notification_event_body(*, event_id: str) -> Dict[str, Any]:
    return {
        "event_type": EVENT_CREATED_EVENT,
        "version": EVENT_NOTIFICATION_EVENT_VERSION,
        "event_id": event_id,
    }


def build_event_reminder_event_body(
    *, event_id: str, reminder_type: str, fire_at: str,
) -> Dict[str, Any]:
    return {
        "event_type": EVENT_REMINDER_EVENT,
        "version": EVENT_NOTIFICATION_EVENT_VERSION,
        "event_id": event_id,
        "reminder_type": reminder_type,
        # The exact fire_at this dispatch was claimed for. A message that
        # outlives a cancel or reschedule of the same (event_id,
        # reminder_type) row - e.g. left queued past a visibility timeout,
        # or delayed until after that row is legitimately re-claimed for a
        # new schedule - can then be recognized as stale by the consumer
        # even though the row itself looks valid again by the time it's
        # processed.
        "fire_at": fire_at,
    }


def build_event_announcement_event_body(
    *,
    event_id: str,
    announcement_id: str,
    audience: str,
    title: str,
    body: str,
) -> Dict[str, Any]:
    """One organizer-written push.

    The copy rides in the message rather than being looked up later: it is
    typed by a person for this moment and is not stored anywhere else, so a
    consumer that had only ids would have nothing to render.

    announcement_id makes each send its own delivery. Two sends of identical
    text are two announcements, while a redelivered message is the same one -
    which is exactly the distinction per-device idempotency needs.
    """
    return {
        "event_type": EVENT_ANNOUNCEMENT_EVENT,
        "version": EVENT_NOTIFICATION_EVENT_VERSION,
        "event_id": event_id,
        "announcement_id": announcement_id,
        "audience": audience,
        "title": title,
        "body": body,
    }


def send_event_notification_message(message_body: Dict[str, Any]) -> str:
    queue_url = get_event_notification_sqs_queue_url()
    try:
        return send_sqs_message(queue_url, message_body, service_name="Event")
    except HTTPException as e:
        raise RuntimeError(e.detail) from e
