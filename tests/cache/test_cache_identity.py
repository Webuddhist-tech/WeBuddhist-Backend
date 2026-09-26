from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from jose import JWTError

from pecha_api.cache.cache_identity import cache_identity_from_token


@pytest.mark.asyncio
async def test_no_token_is_anonymous():
    assert await cache_identity_from_token(None) is None
    assert await cache_identity_from_token("") is None


@pytest.mark.asyncio
async def test_identity_comes_from_the_verified_payload():
    user_id = uuid4()
    with patch(
        "pecha_api.cache.cache_identity.validate_token",
        return_value={"sub": str(user_id), "iss": "https://issuer/"},
    ):
        assert await cache_identity_from_token("token") == f"https://issuer/|{user_id}"


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

    alice, bob = str(uuid4()), str(uuid4())
    with patch("pecha_api.cache.cache_identity.validate_token", side_effect=_payload):
        assert await cache_identity_from_token(alice) != await cache_identity_from_token(bob)


@pytest.mark.parametrize(
    "payload,expected",
    [
        ({"sub": "auth0|same", "phone_number": "+100", "email": "a@b.c", "iss": "i"}, "i|phone:+100"),
        ({"sub": "11111111-1111-1111-1111-111111111111", "phone_number": "+100", "iss": "i"},
         "i|11111111-1111-1111-1111-111111111111"),
        ({"sub": "auth0|same", "phone_number": "+200", "iss": "i"}, "i|phone:+200"),
        ({"sub": "auth0|same", "email": "a@b.c", "iss": "i"}, "i|email:a@b.c"),
        ({"email": "a@b.c", "iss": "i"}, "i|email:a@b.c"),
        ({"phone_number": "+100", "iss": "i"}, "i|phone:+100"),
        ({"sub": "auth0|same", "iss": "i"}, None),
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
        return_value={"sub": "11111111-1111-1111-1111-111111111111", "iss": "i"},
    ) as mock_threadpool:
        assert await cache_identity_from_token("token") == "i|11111111-1111-1111-1111-111111111111"
    mock_threadpool.assert_awaited_once()
