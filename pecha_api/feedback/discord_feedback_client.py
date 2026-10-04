import json
import logging
from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

import httpx

from pecha_api.config import get

logger = logging.getLogger(__name__)

# Discord's own limits on an embed: past these the whole post is rejected.
EMBED_DESCRIPTION_MAX_LENGTH = 4096
EMBED_FIELD_VALUE_MAX_LENGTH = 1024
EMBED_COLOR = 0xF1B24A
REQUEST_TIMEOUT_SECONDS = 15.0


@dataclass(frozen=True)
class FeedbackImage:
    filename: str
    content_type: str
    data: bytes


@dataclass(frozen=True)
class FeedbackNotification:
    feedback_id: UUID
    user_id: UUID
    user_email: Optional[str]
    content: str
    platform: Optional[str]
    app_version: Optional[str]
    images: List[FeedbackImage]


def _field(name: str, value: Optional[str]) -> dict:
    # Discord rejects an empty field value, so a missing one is spelled out.
    text = (value or "").strip() or "-"
    return {"name": name, "value": text[:EMBED_FIELD_VALUE_MAX_LENGTH], "inline": True}


def build_payload(notification: FeedbackNotification) -> dict:
    fields = [
        _field("User ID", str(notification.user_id)),
        _field("App version", notification.app_version),
        _field("Platform", notification.platform),
        _field("Feedback ID", str(notification.feedback_id)),
    ]
    if notification.user_email:
        fields.insert(1, _field("Email", notification.user_email))

    return {
        # Feedback is user-written text: never let it ping @everyone or a role.
        "allowed_mentions": {"parse": []},
        "embeds": [
            {
                "description": notification.content[:EMBED_DESCRIPTION_MAX_LENGTH],
                "color": EMBED_COLOR,
                "fields": fields,
            }
        ],
        "attachments": [
            {"id": index, "filename": image.filename}
            for index, image in enumerate(notification.images)
        ],
    }


def send_feedback_to_discord(notification: FeedbackNotification) -> None:
    """Post a stored feedback to the Discord webhook, if one is configured.

    Runs after the feedback is already saved, so nothing here may raise: a
    missing webhook, a Discord outage or a rate limit only costs the
    notification, never the feedback.
    """
    webhook_url = get("DISCORD_FEEDBACK_WEBHOOK_URL").strip()
    if not webhook_url:
        return

    payload = build_payload(notification)
    # `payload_json` is only read from a multipart body. Without files httpx
    # would send it url-encoded, which Discord ignores, so a text-only
    # feedback goes as plain JSON instead.
    if notification.images:
        request_body = {
            "data": {"payload_json": json.dumps(payload)},
            "files": [
                (f"files[{index}]", (image.filename, image.data, image.content_type))
                for index, image in enumerate(notification.images)
            ],
        }
    else:
        request_body = {"json": payload}

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.post(webhook_url, params={"wait": "true"}, **request_body)
            response.raise_for_status()
    except httpx.HTTPStatusError as error:
        logger.error(
            "Discord rejected feedback %s: %s %s",
            notification.feedback_id,
            error.response.status_code,
            error.response.text[:500],
        )
    except Exception:
        logger.exception("Failed to send feedback %s to Discord", notification.feedback_id)
