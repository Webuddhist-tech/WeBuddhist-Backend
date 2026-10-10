import logging
from dataclasses import dataclass
from typing import List, Optional
from uuid import UUID

import httpx

from pecha_api.config import get

logger = logging.getLogger(__name__)

# Discord's own limits on an embed: past these the whole post is rejected.
EMBED_TITLE_MAX_LENGTH = 256
EMBED_DESCRIPTION_MAX_LENGTH = 4096
EMBED_FIELD_VALUE_MAX_LENGTH = 1024
EMBED_COLOR = 0xA51C21
REQUEST_TIMEOUT_SECONDS = 15.0
TEXT_REQUESTS_STUDIO_PATH = "/admin/text-requests"


@dataclass(frozen=True)
class TextRequestAttachmentLink:
    filename: str
    size: int
    url: str


@dataclass(frozen=True)
class TextRequestNotification:
    request_id: UUID
    requester_name: Optional[str]
    requester_email: Optional[str]
    group_name: Optional[str]
    collection_name: Optional[str]
    message: str
    attachments: List[TextRequestAttachmentLink]


def _field(name: str, value: Optional[str], inline: bool = True) -> dict:
    # Discord rejects an empty field value, so a missing one is spelled out.
    text = (value or "").strip() or "-"
    return {"name": name, "value": text[:EMBED_FIELD_VALUE_MAX_LENGTH], "inline": inline}


def _format_size(size: int) -> str:
    if size >= 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{max(1, round(size / 1024))} KB"


def _attachments_value(attachments: List[TextRequestAttachmentLink]) -> str:
    """One markdown link per file, stopping before the field limit so a link
    is never cut in half."""
    lines: List[str] = []
    used = 0
    for index, attachment in enumerate(attachments):
        # Square brackets would end the link text early.
        name = attachment.filename.replace("[", "(").replace("]", ")")
        line = f"[{name}]({attachment.url}) ({_format_size(attachment.size)})"
        remaining = len(attachments) - index - 1
        suffix = f"\n... and {remaining} more in Studio" if remaining else ""
        if used + len(line) + 1 + len(suffix) > EMBED_FIELD_VALUE_MAX_LENGTH:
            lines.append(f"... and {len(attachments) - index} more in Studio")
            break
        lines.append(line)
        used += len(line) + 1
    return "\n".join(lines)


def build_payload(notification: TextRequestNotification) -> dict:
    fields = [
        _field("Requested by", notification.requester_name),
        _field("Email", notification.requester_email),
        _field("Space", notification.group_name),
        _field("Chant collection", notification.collection_name),
        _field("Request ID", str(notification.request_id), inline=False),
    ]
    if notification.attachments:
        fields.append(
            _field(
                f"Attachments ({len(notification.attachments)}) - links expire, Studio always has fresh ones",
                _attachments_value(notification.attachments),
                inline=False,
            )
        )

    embed = {
        "title": "New text request"[:EMBED_TITLE_MAX_LENGTH],
        "description": notification.message[:EMBED_DESCRIPTION_MAX_LENGTH],
        "color": EMBED_COLOR,
        "fields": fields,
    }
    studio_base_url = get("WEBUDDHIST_STUDIO_BASE_URL").strip().rstrip("/")
    if studio_base_url:
        embed["url"] = f"{studio_base_url}{TEXT_REQUESTS_STUDIO_PATH}"

    return {
        # The message is user-written text: never let it ping @everyone or a role.
        "allowed_mentions": {"parse": []},
        "embeds": [embed],
    }


def send_text_request_to_discord(notification: TextRequestNotification) -> None:
    """Post a stored text request to the Discord webhook, if one is configured.

    Runs after the request is already saved, so nothing here may raise: a
    missing webhook, a Discord outage or a rate limit only costs the
    notification, never the request.
    """
    webhook_url = get("DISCORD_TEXT_REQUEST_WEBHOOK_URL").strip()
    if not webhook_url:
        return

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.post(
                webhook_url,
                params={"wait": "true"},
                json=build_payload(notification),
            )
            response.raise_for_status()
    except httpx.HTTPStatusError as error:
        logger.error(
            "Discord rejected text request %s: %s %s",
            notification.request_id,
            error.response.status_code,
            error.response.text[:500],
        )
    except Exception:
        logger.exception("Failed to send text request %s to Discord", notification.request_id)
