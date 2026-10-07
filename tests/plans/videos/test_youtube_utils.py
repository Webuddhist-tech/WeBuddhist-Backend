from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from pecha_api.plans.videos import youtube_utils
from pecha_api.plans.videos.youtube_utils import (
    fetch_youtube_durations,
    lookup_youtube_duration_seconds,
    parse_iso8601_duration,
)

UTILS = "pecha_api.plans.videos.youtube_utils"


def test_parse_iso8601_duration_hours_minutes_seconds():
    assert parse_iso8601_duration("PT1H2M3S") == 3723
    assert parse_iso8601_duration("PT4M13S") == 253
    assert parse_iso8601_duration("PT15S") == 15


def test_parse_iso8601_duration_live_or_zero_is_none():
    assert parse_iso8601_duration("P0D") is None
    assert parse_iso8601_duration("PT0S") is None
    assert parse_iso8601_duration(None) is None
    assert parse_iso8601_duration("not-a-duration") is None


def test_fetch_youtube_durations_skips_when_api_key_missing():
    with patch(f"{UTILS}.config.get", return_value=""):
        assert fetch_youtube_durations(["AAAAAAAAAAA"]) == {}


def test_fetch_youtube_durations_maps_content_details():
    response = MagicMock()
    response.json.return_value = {
        "items": [
            {"id": "AAAAAAAAAAA", "contentDetails": {"duration": "PT4M13S"}},
            {"id": "BBBBBBBBBBB", "contentDetails": {"duration": "P0D"}},
        ]
    }
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.get.return_value = response
    client.__enter__.return_value = client
    client.__exit__.return_value = False

    with patch(f"{UTILS}.config.get", return_value="test-key"), patch(
        f"{UTILS}.httpx.Client", return_value=client
    ):
        assert fetch_youtube_durations(["AAAAAAAAAAA", "BBBBBBBBBBB"]) == {
            "AAAAAAAAAAA": 253
        }


def test_fetch_youtube_durations_http_error_returns_empty():
    client = MagicMock()
    client.get.side_effect = RuntimeError("network")
    client.__enter__.return_value = client
    client.__exit__.return_value = False

    with patch(f"{UTILS}.config.get", return_value="test-key"), patch(
        f"{UTILS}.httpx.Client", return_value=client
    ):
        assert fetch_youtube_durations(["AAAAAAAAAAA"]) == {}


def test_failed_lookup_entries_are_pruned_after_ttl():
    youtube_utils._failed_lookup_until.clear()
    past = datetime.now(timezone.utc) - timedelta(minutes=1)
    youtube_utils._failed_lookup_until["AAAAAAAAAAA"] = past

    with patch(f"{UTILS}.config.get", return_value=""):
        fetch_youtube_durations(["AAAAAAAAAAA"])

    assert "AAAAAAAAAAA" not in youtube_utils._failed_lookup_until


def test_malformed_youtube_payload_does_not_raise_from_lookup():
    response = MagicMock()
    response.json.return_value = {"items": [{"id": "AAAAAAAAAAA", "contentDetails": "bad"}]}
    response.raise_for_status.return_value = None
    client = MagicMock()
    client.get.return_value = response
    client.__enter__.return_value = client
    client.__exit__.return_value = False

    with patch(f"{UTILS}.config.get", return_value="test-key"), patch(
        f"{UTILS}.httpx.Client", return_value=client
    ):
        assert lookup_youtube_duration_seconds("AAAAAAAAAAA") is None
