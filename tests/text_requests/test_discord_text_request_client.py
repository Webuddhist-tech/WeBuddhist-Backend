from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx

from pecha_api.text_requests.discord_text_request_client import (
    EMBED_FIELD_VALUE_MAX_LENGTH,
    TextRequestAttachmentLink,
    TextRequestNotification,
    build_payload,
    send_text_request_to_discord,
)

CLIENT = "pecha_api.text_requests.discord_text_request_client"


def _notification(attachments=None, message="Please add the Heart Sutra") -> TextRequestNotification:
    return TextRequestNotification(
        request_id=uuid4(),
        requester_name="Tenzin Dolma",
        requester_email="author@example.com",
        group_name="Sangha",
        collection_name=None,
        message=message,
        attachments=attachments or [],
    )


def test_payload_has_requester_links_and_no_mentions():
    payload = build_payload(
        _notification(
            attachments=[TextRequestAttachmentLink(filename="a[1].pdf", size=2 * 1024 * 1024, url="https://s3/a")]
        )
    )
    embed = payload["embeds"][0]
    fields = {field["name"]: field["value"] for field in embed["fields"]}
    assert payload["allowed_mentions"] == {"parse": []}
    assert embed["description"] == "Please add the Heart Sutra"
    assert fields["Requested by"] == "Tenzin Dolma"
    assert fields["Chant collection"] == "-"
    attachments_value = next(v for k, v in fields.items() if k.startswith("Attachments"))
    assert attachments_value == "[a(1).pdf](https://s3/a) (2.0 MB)"
    assert embed["url"].endswith("/admin/text-requests")


def test_attachment_field_stays_within_discord_limit():
    links = [
        TextRequestAttachmentLink(filename=f"file-{i}.pdf", size=1000, url="https://s3/" + "x" * 200)
        for i in range(10)
    ]
    payload = build_payload(_notification(attachments=links))
    value = next(f["value"] for f in payload["embeds"][0]["fields"] if f["name"].startswith("Attachments"))
    assert len(value) <= EMBED_FIELD_VALUE_MAX_LENGTH
    assert "more in Studio" in value


def test_send_skips_when_webhook_not_configured():
    with patch(f"{CLIENT}.get", return_value=""), patch(f"{CLIENT}.httpx.Client") as client:
        send_text_request_to_discord(_notification())
    client.assert_not_called()


def test_send_posts_json_and_swallows_errors():
    response = MagicMock()
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "bad", request=MagicMock(), response=MagicMock(status_code=400, text="nope")
    )
    client = MagicMock()
    client.__enter__.return_value = client
    client.post.return_value = response
    with patch(f"{CLIENT}.get", return_value="https://discord/webhook"), patch(
        f"{CLIENT}.httpx.Client", return_value=client
    ):
        send_text_request_to_discord(_notification())
    assert "json" in client.post.call_args.kwargs
