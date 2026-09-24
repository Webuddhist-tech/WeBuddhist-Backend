"""A cached response must not outlive the signed URLs it carries."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pecha_api.cache import cache_repository
from pecha_api.cache.presigned_expiry import seconds_until_first_expiry


def _signed_url(signed_at: datetime, lifetime_seconds: int, key: str = "img/a.jpg") -> str:
    stamp = signed_at.strftime("%Y%m%dT%H%M%SZ")
    return (
        f"https://bucket.s3.amazonaws.com/{key}"
        "?X-Amz-Algorithm=AWS4-HMAC-SHA256"
        f"&X-Amz-Credential=AKIA%2F20260924%2Fus-east-1%2Fs3%2Faws4_request"
        f"&X-Amz-Date={stamp}&X-Amz-Expires={lifetime_seconds}"
        "&X-Amz-SignedHeaders=host&X-Amz-Signature=deadbeef"
    )


def test_payload_without_signed_urls_is_left_alone():
    payload = json.dumps({"title": "A text", "url": "https://example.com/page"})
    assert seconds_until_first_expiry(payload) is None


def test_reads_the_deadline_out_of_a_sigv4_url():
    now = datetime.now(timezone.utc)
    payload = json.dumps({"img_url": _signed_url(now, 3600)})

    remaining = seconds_until_first_expiry(payload, now=now)

    assert 3590 <= remaining <= 3600


def test_takes_the_earliest_deadline_in_the_payload():
    now = datetime.now(timezone.utc)
    payload = json.dumps({
        "avatar": _signed_url(now, 86400, key="a.jpg"),
        "media": _signed_url(now - timedelta(hours=1), 7200, key="b.jpg"),
    })

    remaining = seconds_until_first_expiry(payload, now=now)

    assert 3590 <= remaining <= 3600, "the hour left on the older signature governs"


def test_an_already_lapsed_signature_reads_as_zero():
    now = datetime.now(timezone.utc)
    payload = json.dumps({"img_url": _signed_url(now - timedelta(hours=5), 3600)})

    assert seconds_until_first_expiry(payload, now=now) == 0


def test_absolute_expires_parameter_is_understood():
    now = datetime.now(timezone.utc)
    deadline = int((now + timedelta(seconds=600)).timestamp())
    payload = json.dumps(
        {"img_url": f"https://bucket.s3.amazonaws.com/a.jpg?X-Amz-Foo=1&Expires={deadline}"}
    )

    assert 590 <= seconds_until_first_expiry(payload, now=now) <= 600


def test_a_malformed_deadline_does_not_shorten_anything():
    payload = json.dumps(
        {"img_url": "https://bucket.s3.amazonaws.com/a.jpg?X-Amz-Date=nonsense&X-Amz-Expires=x"}
    )

    assert seconds_until_first_expiry(payload) is None


@pytest.mark.asyncio
async def test_timeout_is_cut_to_the_life_left_in_the_signature():
    """The bug: content cached for 3.5h while its URLs were signed for one."""
    now = datetime.now(timezone.utc)
    payload = {"img_url": _signed_url(now, 3600)}
    client = MagicMock()
    client.setex = AsyncMock(return_value=True)

    with patch.object(cache_repository, "get_client", return_value=client), \
         patch.object(cache_repository, "_circuit_is_open", return_value=False), \
         patch.object(cache_repository.config, "get_int", return_value=1800), \
         patch.object(cache_repository.config, "get", return_value="pecha:"):
        assert await cache_repository.set_cache("k", payload, cache_time_out=12600)

    _, ttl, _ = client.setex.call_args.args
    assert ttl <= 1800, "3600s of signature minus a 1800s margin"


@pytest.mark.asyncio
async def test_a_shorter_timeout_than_the_signature_is_kept():
    now = datetime.now(timezone.utc)
    payload = {"img_url": _signed_url(now, 86400)}
    client = MagicMock()
    client.setex = AsyncMock(return_value=True)

    with patch.object(cache_repository, "get_client", return_value=client), \
         patch.object(cache_repository, "_circuit_is_open", return_value=False), \
         patch.object(cache_repository.config, "get_int", return_value=1800), \
         patch.object(cache_repository.config, "get", return_value="pecha:"):
        await cache_repository.set_cache("k", payload, cache_time_out=60)

    _, ttl, _ = client.setex.call_args.args
    assert ttl == 60, "the caller's own freshness requirement still governs"


@pytest.mark.asyncio
async def test_a_response_with_nothing_left_on_its_urls_is_not_cached():
    now = datetime.now(timezone.utc)
    payload = {"img_url": _signed_url(now - timedelta(hours=2), 3600)}
    client = MagicMock()
    client.setex = AsyncMock(return_value=True)

    with patch.object(cache_repository, "get_client", return_value=client), \
         patch.object(cache_repository, "_circuit_is_open", return_value=False), \
         patch.object(cache_repository.config, "get_int", return_value=1800), \
         patch.object(cache_repository.config, "get", return_value="pecha:"):
        assert await cache_repository.set_cache("k", payload, cache_time_out=12600) is False

    client.setex.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_image_free_payload_keeps_its_long_timeout():
    """Calendars are cached for 30 days on purpose; they carry no signatures."""
    client = MagicMock()
    client.setex = AsyncMock(return_value=True)

    with patch.object(cache_repository, "get_client", return_value=client), \
         patch.object(cache_repository, "_circuit_is_open", return_value=False), \
         patch.object(cache_repository.config, "get", return_value="pecha:"):
        await cache_repository.set_cache("k", {"days": [1, 2]}, cache_time_out=2592000)

    _, ttl, _ = client.setex.call_args.args
    assert ttl == 2592000


def test_signing_lifetime_is_clamped_to_what_aws_accepts():
    from pecha_api.uploads import S3_utils

    with patch.object(S3_utils, "get_int", return_value=30 * 24 * 60 * 60):
        assert S3_utils.presigned_url_expiry_seconds() == S3_utils.MAX_PRESIGNED_EXPIRY_SECONDS

    with patch.object(S3_utils, "get_int", return_value=86400):
        assert S3_utils.presigned_url_expiry_seconds() == 86400
