from typing import Any, Dict

from pecha_api.config import get
from pecha_api.shared.sqs_client import send_sqs_message

PRAYER_TRANSLATION_REQUESTED_EVENT = "PRAYER_TRANSLATION_REQUESTED"
PRAYER_TRANSLATION_EVENT_VERSION = 1


def get_prayer_translation_sqs_queue_url() -> str:
    return get("PRAYER_TRANSLATION_SQS_QUEUE_URL").strip()


def is_prayer_translation_sqs_configured() -> bool:
    return bool(get_prayer_translation_sqs_queue_url())


def build_prayer_translation_event_body(*, message_id: str) -> Dict[str, Any]:
    return {
        "event_type": PRAYER_TRANSLATION_REQUESTED_EVENT,
        "version": PRAYER_TRANSLATION_EVENT_VERSION,
        "message_id": message_id,
    }


def send_prayer_translation_message(message_body: Dict[str, Any]) -> str:
    queue_url = get_prayer_translation_sqs_queue_url()
    return send_sqs_message(
        queue_url, message_body, service_name="PrayerTranslation"
    )
