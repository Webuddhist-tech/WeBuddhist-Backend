from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from jose import JWTError

from pecha_api.cache.cache_identity import (
    _identity_from_token,
    cache_identity_from_token,
)


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
    to be refetched, and resolving an ambiguous phone claim queries the
    database; on the event loop either one stalls every other request."""
    with patch(
        "pecha_api.cache.cache_identity.run_in_threadpool",
        new_callable=AsyncMock,
        return_value="i|11111111-1111-1111-1111-111111111111",
    ) as mock_threadpool:
        assert await cache_identity_from_token("token") == "i|11111111-1111-1111-1111-111111111111"
    mock_threadpool.assert_awaited_once_with(_identity_from_token, "token")


# A token carrying both a phone and an email is the one case the payload does
# not settle: `resolve_user_from_payload` tries the phone and falls through to
# the email when nobody owns it, so the key has to follow the same rule or the
# two users end up sharing it.
_BOTH_CLAIMS = {
    "sub": "auth0|same",
    "phone_number": "+100",
    "email": "a@b.c",
    "iss": "i",
}


@pytest.mark.asyncio
async def test_an_unlinked_phone_is_keyed_on_the_email_that_resolves_it():
    with patch(
        "pecha_api.cache.cache_identity.validate_token", return_value=_BOTH_CLAIMS
    ), patch(
        "pecha_api.cache.cache_identity.get_user_by_phone", return_value=None
    ):
        assert await cache_identity_from_token("token") == "i|email:a@b.c"


@pytest.mark.asyncio
async def test_a_linked_phone_is_keyed_on_the_phone():
    with patch(
        "pecha_api.cache.cache_identity.validate_token", return_value=_BOTH_CLAIMS
    ), patch(
        "pecha_api.cache.cache_identity.get_user_by_phone", return_value=object()
    ):
        assert await cache_identity_from_token("token") == "i|phone:+100"


@pytest.mark.asyncio
async def test_linking_a_phone_moves_the_key_off_the_previous_owner():
    """The leak this guards: the email owner's entry must not be handed to
    whoever links that phone number afterwards."""
    with patch(
        "pecha_api.cache.cache_identity.validate_token", return_value=_BOTH_CLAIMS
    ):
        with patch(
            "pecha_api.cache.cache_identity.get_user_by_phone", return_value=None
        ):
            before = await cache_identity_from_token("token")
        with patch(
            "pecha_api.cache.cache_identity.get_user_by_phone", return_value=object()
        ):
            after = await cache_identity_from_token("token")
    assert before != after


@pytest.mark.asyncio
async def test_a_phone_only_token_is_keyed_without_a_query():
    """The query is confined to the ambiguous case; every other token is keyed
    from the payload alone."""
    def _fail(**_kwargs):
        raise AssertionError("the database must not be consulted here")

    with patch(
        "pecha_api.cache.cache_identity.validate_token",
        return_value={"sub": "auth0|same", "phone_number": "+100", "iss": "i"},
    ), patch("pecha_api.cache.cache_identity.get_user_by_phone", _fail):
        assert await cache_identity_from_token("token") == "i|phone:+100"


@pytest.mark.asyncio
async def test_a_failed_lookup_keys_on_the_phone_rather_than_going_anonymous():
    """Anonymous is the shared segment on these endpoints, so a database blip
    must not drop a real user into it."""
    with patch(
        "pecha_api.cache.cache_identity.validate_token", return_value=_BOTH_CLAIMS
    ), patch(
        "pecha_api.cache.cache_identity.SessionLocal",
        side_effect=RuntimeError("no database"),
    ):
        assert await cache_identity_from_token("token") == "i|phone:+100"
