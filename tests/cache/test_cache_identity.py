from unittest.mock import AsyncMock, patch

import pytest
from jose import JWTError

from pecha_api.cache.cache_identity import cache_identity_from_token


@pytest.mark.asyncio
async def test_no_token_is_anonymous():
    assert await cache_identity_from_token(None) is None
    assert await cache_identity_from_token("") is None


@pytest.mark.asyncio
async def test_identity_comes_from_the_verified_payload():
    with patch(
        "pecha_api.cache.cache_identity.validate_token",
        return_value={"sub": "user-123", "iss": "https://issuer/"},
    ):
        assert await cache_identity_from_token("token") == "https://issuer/|user-123"


@pytest.mark.asyncio
async def test_an_unverifiable_token_is_anonymous_not_an_error():
    """A bad token already means anonymous in these endpoints; the cache key
    must not disagree with that, and must not raise."""
    with patch(
        "pecha_api.cache.cache_identity.validate_token",
        side_effect=JWTError("bad signature"),
    ):
        assert await cache_identity_from_token("forged") is None


@pytest.mark.asyncio
async def test_identity_is_never_taken_without_verification():
    """The security property: a forged token naming someone else must not
    produce that person's key. validate_token is what rejects it, so it has
    to be called every time."""
    with patch(
        "pecha_api.cache.cache_identity.validate_token",
        side_effect=JWTError("bad signature"),
    ) as mock_validate:
        assert await cache_identity_from_token("header.claims-say-victim.sig") is None
    mock_validate.assert_called_once()


@pytest.mark.asyncio
async def test_two_users_get_different_identities():
    def _payload(token):
        return {"sub": token, "iss": "https://issuer/"}

    with patch("pecha_api.cache.cache_identity.validate_token", side_effect=_payload):
        assert await cache_identity_from_token("alice") != await cache_identity_from_token("bob")


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"sub": "s", "iss": "i"}, "i|s"),
        ({"email": "a@b.c", "iss": "i"}, "i|a@b.c"),
        ({"phone_number": "+100", "iss": "i"}, "i|+100"),
        ({"iss": "i"}, None),
    ],
)
@pytest.mark.asyncio
async def test_falls_back_through_the_claims_that_identify_someone(payload, expected):
    with patch("pecha_api.cache.cache_identity.validate_token", return_value=payload):
        assert await cache_identity_from_token("token") == expected


@pytest.mark.asyncio
async def test_verification_runs_in_a_worker_thread():
    """Auth0 verification can make a blocking HTTP call when the key set has
    to be refetched; on the event loop that stalls every other request."""
    with patch(
        "pecha_api.cache.cache_identity.run_in_threadpool",
        new_callable=AsyncMock,
        return_value={"sub": "s", "iss": "i"},
    ) as mock_threadpool:
        assert await cache_identity_from_token("token") == "i|s"
    mock_threadpool.assert_awaited_once()
