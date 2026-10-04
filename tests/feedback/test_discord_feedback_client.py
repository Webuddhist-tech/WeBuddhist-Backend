import json
from unittest.mock import MagicMock, patch
from uuid import uuid4

import httpx

from pecha_api.feedback.discord_feedback_client import (
    EMBED_DESCRIPTION_MAX_LENGTH,
    FeedbackImage,
    FeedbackNotification,
    build_payload,
    send_feedback_to_discord,
)

CLIENT = "pecha_api.feedback.discord_feedback_client.httpx.Client"
WEBHOOK_URL = "https://discord.com/api/webhooks/1/abc"


def _notification(**overrides) -> FeedbackNotification:
    values = dict(
        feedback_id=uuid4(),
        user_id=uuid4(),
        user_email="user@example.com",
        content="Please add dark mode @everyone",
        platform="ios 17.2",
        app_version="2.3.1",
        images=[],
    )
    values.update(overrides)
    return FeedbackNotification(**values)


def _mock_client():
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


def _fields(payload: dict) -> dict:
    return {field["name"]: field["value"] for field in payload["embeds"][0]["fields"]}


def test_build_payload_carries_feedback_and_blocks_mentions():
    notification = _notification()

    payload = build_payload(notification)

    assert payload["allowed_mentions"] == {"parse": []}
    assert payload["embeds"][0]["description"] == notification.content
    assert _fields(payload) == {
        "User ID": str(notification.user_id),
        "Email": "user@example.com",
        "App version": "2.3.1",
        "Platform": "ios 17.2",
        "Feedback ID": str(notification.feedback_id),
    }
    assert payload["attachments"] == []


def test_build_payload_fills_missing_fields_and_truncates_content():
    notification = _notification(
        user_email=None,
        platform=None,
        app_version="",
        content="x" * (EMBED_DESCRIPTION_MAX_LENGTH + 50),
    )

    payload = build_payload(notification)

    fields = _fields(payload)
    assert "Email" not in fields
    assert fields["Platform"] == "-"
    assert fields["App version"] == "-"
    assert len(payload["embeds"][0]["description"]) == EMBED_DESCRIPTION_MAX_LENGTH


def test_send_skips_when_webhook_not_configured(monkeypatch):
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", "")

    with patch(CLIENT) as client_class:
        send_feedback_to_discord(_notification())

    client_class.assert_not_called()


def test_send_text_only_feedback_as_json(monkeypatch):
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", WEBHOOK_URL)
    client = _mock_client()
    notification = _notification()

    with patch(CLIENT, return_value=client):
        send_feedback_to_discord(notification)

    kwargs = client.post.call_args.kwargs
    assert client.post.call_args.args == (WEBHOOK_URL,)
    assert kwargs["params"] == {"wait": "true"}
    assert kwargs["json"] == build_payload(notification)
    assert "files" not in kwargs


def test_send_feedback_with_images_as_multipart(monkeypatch):
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", WEBHOOK_URL)
    client = _mock_client()
    images = [
        FeedbackImage(filename="feedback-1.jpg", content_type="image/jpeg", data=b"one"),
        FeedbackImage(filename="feedback-2.png", content_type="image/png", data=b"two"),
    ]

    with patch(CLIENT, return_value=client):
        send_feedback_to_discord(_notification(images=images))

    kwargs = client.post.call_args.kwargs
    assert kwargs["files"] == [
        ("files[0]", ("feedback-1.jpg", b"one", "image/jpeg")),
        ("files[1]", ("feedback-2.png", b"two", "image/png")),
    ]
    payload = json.loads(kwargs["data"]["payload_json"])
    assert payload["attachments"] == [
        {"id": 0, "filename": "feedback-1.jpg"},
        {"id": 1, "filename": "feedback-2.png"},
    ]


def test_send_swallows_discord_errors(monkeypatch):
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", WEBHOOK_URL)
    client = _mock_client()
    request = httpx.Request("POST", WEBHOOK_URL)
    response = httpx.Response(429, request=request, text="rate limited")
    client.post.return_value = response

    with patch(CLIENT, return_value=client):
        send_feedback_to_discord(_notification())  # must not raise


def test_send_swallows_network_errors(monkeypatch):
    monkeypatch.setenv("DISCORD_FEEDBACK_WEBHOOK_URL", WEBHOOK_URL)
    client = _mock_client()
    client.post.side_effect = httpx.ConnectError("unreachable")

    with patch(CLIENT, return_value=client):
        send_feedback_to_discord(_notification())  # must not raise
