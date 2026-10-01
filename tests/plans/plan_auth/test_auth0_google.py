from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from pecha_api.auth.auth0_google import (
    _decode_auth0_google_token,
    verify_auth0_google_token,
)


def _payload(**overrides):
    base = {
        "sub": "google-oauth2|abc123",
        "aud": "webuddhist-backend",
        "https://webuddhist.com/email": "ada@example.com",
        "https://webuddhist.com/email_verified": True,
        "https://webuddhist.com/given_name": "Ada",
        "https://webuddhist.com/family_name": "Lovelace",
        "iat": datetime.now(timezone.utc).timestamp(),
    }
    base.update(overrides)
    return base


def test_decode_auth0_google_token_strictly_verifies_rs256_issuer_and_audience():
    decode_mock = patch(
        "pecha_api.auth.auth0_google.jwt.get_unverified_header",
        return_value={"alg": "RS256", "kid": "kid-1"},
    )
    keys_mock = patch(
        "pecha_api.auth.auth0_google._get_auth0_google_public_keys",
        return_value={"kid-1": {"kid": "kid-1"}},
    )
    config_mock = patch(
        "pecha_api.auth.auth0_google.get",
        side_effect=lambda key: {
            "AUTH0_SMS_DOMAIN": "tenant.auth0.com",
            "DOMAIN_NAME": "tenant.auth0.com",
            "AUTH0_SMS_AUDIENCE": "webuddhist-backend",
            "AUTH0_AUDIENCE": "webuddhist-backend",
            "CLIENT_ID": "spa-client",
            "AUTH0_ADDITIONAL_CLIENT_IDS": "",
        }.get(key, ""),
    )
    jwt_decode = patch(
        "pecha_api.auth.auth0_google.jwt.decode",
        return_value=_payload(),
    )
    with decode_mock, keys_mock, config_mock, jwt_decode as decode:
        _decode_auth0_google_token("token")

    decode.assert_called_once()
    assert decode.call_args.kwargs["issuer"] == "https://tenant.auth0.com/"
    assert decode.call_args.kwargs["algorithms"] == ["RS256"]


def test_decode_auth0_google_token_rejects_non_rs256_header():
    with patch(
        "pecha_api.auth.auth0_google.jwt.get_unverified_header",
        return_value={"alg": "HS256", "kid": "kid-1"},
    ):
        with pytest.raises(ValueError, match="RS256"):
            _decode_auth0_google_token("token")


def test_verify_auth0_google_token_returns_normalized_identity():
    with patch(
        "pecha_api.auth.auth0_google._decode_auth0_google_token",
        return_value=_payload(),
    ), patch(
        "pecha_api.auth.auth0_google.get",
        side_effect=lambda key: {
            "AUTH0_GOOGLE_EMAIL_CLAIM": "https://webuddhist.com/email",
            "AUTH0_GOOGLE_EMAIL_VERIFIED_CLAIM": "https://webuddhist.com/email_verified",
        }.get(key, ""),
    ), patch(
        "pecha_api.auth.auth0_google.get_int",
        return_value=300,
    ):
        identity = verify_auth0_google_token("token")

    assert identity.subject == "google-oauth2|abc123"
    assert identity.email == "ada@example.com"
    assert identity.first_name == "Ada"
    assert identity.last_name == "Lovelace"


@pytest.mark.parametrize(
    "payload",
    [
        _payload(sub="auth0|abc"),
        _payload(**{"https://webuddhist.com/email": None, "email": None}),
    ],
)
def test_verify_auth0_google_token_rejects_untrusted_claims(payload):
    with patch(
        "pecha_api.auth.auth0_google._decode_auth0_google_token",
        return_value=payload,
    ), patch(
        "pecha_api.auth.auth0_google.get",
        side_effect=lambda key: {
            "AUTH0_GOOGLE_EMAIL_CLAIM": "https://webuddhist.com/email",
            "AUTH0_GOOGLE_EMAIL_VERIFIED_CLAIM": "https://webuddhist.com/email_verified",
        }.get(key, ""),
    ), patch(
        "pecha_api.auth.auth0_google.get_int",
        return_value=300,
    ):
        with pytest.raises(HTTPException) as exc:
            verify_auth0_google_token("token")

    assert exc.value.detail == "Invalid Auth0 Google token"
