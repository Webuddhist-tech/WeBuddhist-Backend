"""How long Auth0's signing keys stay trusted once refreshes start failing."""

from unittest.mock import patch

import pytest

from pecha_api.auth import auth_repository


@pytest.fixture(autouse=True)
def _clear_jwks_cache():
    auth_repository._jwks_cache["keys"] = None
    auth_repository._jwks_cache["fetched_at"] = 0.0
    yield
    auth_repository._jwks_cache["keys"] = None
    auth_repository._jwks_cache["fetched_at"] = 0.0


KEYS = {"kid-1": {"kty": "RSA", "kid": "kid-1"}}


def _prime_cache(at: float = 1000.0):
    with patch.object(auth_repository, "_fetch_auth0_public_key", return_value=KEYS), \
         patch.object(auth_repository.time, "monotonic", return_value=at):
        assert auth_repository.get_auth0_public_key() == KEYS


def test_a_fresh_key_set_is_served_without_refetching():
    _prime_cache()
    with patch.object(auth_repository, "_fetch_auth0_public_key") as mock_fetch, \
         patch.object(auth_repository.time, "monotonic", return_value=1100.0):
        assert auth_repository.get_auth0_public_key() == KEYS
    mock_fetch.assert_not_called()


def test_a_brief_outage_is_ridden_out_on_the_cached_keys():
    """Auth0 unreachable for a few minutes must not fail every login."""
    _prime_cache()
    with patch.object(auth_repository, "_fetch_auth0_public_key", side_effect=OSError("boom")), \
         patch.object(auth_repository.time, "monotonic", return_value=1000.0 + 1200):
        assert auth_repository.get_auth0_public_key() == KEYS


def test_stale_keys_are_served_right_up_to_the_grace_limit():
    _prime_cache()
    limit = auth_repository.JWKS_CACHE_TTL_SECONDS + auth_repository.JWKS_STALE_GRACE_SECONDS
    with patch.object(auth_repository, "_fetch_auth0_public_key", side_effect=OSError("boom")), \
         patch.object(auth_repository.time, "monotonic", return_value=1000.0 + limit):
        assert auth_repository.get_auth0_public_key() == KEYS


def test_keys_stop_being_trusted_once_the_grace_window_passes():
    """A key Auth0 has withdrawn must not stay valid forever just because we
    can no longer reach the tenant that would have told us."""
    _prime_cache()
    limit = auth_repository.JWKS_CACHE_TTL_SECONDS + auth_repository.JWKS_STALE_GRACE_SECONDS
    with patch.object(auth_repository, "_fetch_auth0_public_key", side_effect=OSError("boom")), \
         patch.object(auth_repository.time, "monotonic", return_value=1000.0 + limit + 1):
        with pytest.raises(OSError):
            auth_repository.get_auth0_public_key()


def test_a_successful_refresh_resets_the_clock():
    _prime_cache()
    limit = auth_repository.JWKS_CACHE_TTL_SECONDS + auth_repository.JWKS_STALE_GRACE_SECONDS
    rotated = {"kid-2": {"kty": "RSA", "kid": "kid-2"}}

    with patch.object(auth_repository, "_fetch_auth0_public_key", return_value=rotated), \
         patch.object(auth_repository.time, "monotonic", return_value=1000.0 + 700):
        assert auth_repository.get_auth0_public_key() == rotated

    with patch.object(auth_repository, "_fetch_auth0_public_key", side_effect=OSError("boom")), \
         patch.object(auth_repository.time, "monotonic", return_value=1000.0 + 700 + limit):
        assert auth_repository.get_auth0_public_key() == rotated


def test_a_first_fetch_failure_still_raises():
    with patch.object(auth_repository, "_fetch_auth0_public_key", side_effect=OSError("boom")):
        with pytest.raises(OSError):
            auth_repository.get_auth0_public_key()


def test_token_verification_fails_closed_on_keys_past_the_grace_window():
    """The end-to-end consequence: the bearer token is refused, not accepted."""
    _prime_cache()
    limit = auth_repository.JWKS_CACHE_TTL_SECONDS + auth_repository.JWKS_STALE_GRACE_SECONDS
    with patch.object(auth_repository, "_fetch_auth0_public_key", side_effect=OSError("boom")), \
         patch.object(auth_repository.time, "monotonic", return_value=1000.0 + limit + 1):
        with pytest.raises(OSError):
            auth_repository.verify_auth0_token("any.token.value")
