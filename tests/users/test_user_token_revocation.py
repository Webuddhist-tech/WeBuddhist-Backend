from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.users.user_resolution import resolve_user_from_payload

ISSUER = "https://pecha.org"
REVOKED_AT = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)


def _resolve(payload: dict, valid_after=REVOKED_AT):
    user = SimpleNamespace(id=uuid4(), tokens_valid_after=valid_after)
    payload = {"sub": str(user.id), "iss": ISSUER, **payload}
    with patch("pecha_api.users.user_resolution.get", return_value=ISSUER), \
         patch("pecha_api.users.user_resolution.get_user_by_id", return_value=user):
        return user, resolve_user_from_payload(db=None, payload=payload, unauthorized_detail="bad token")


def test_token_issued_before_revocation_is_rejected() -> None:
    with pytest.raises(HTTPException) as error:
        _resolve({"iat": int((REVOKED_AT - timedelta(minutes=5)).timestamp())})
    assert error.value.status_code == 401


def test_token_issued_in_the_revoking_second_or_without_iat_is_rejected() -> None:
    for payload in ({"iat": int(REVOKED_AT.timestamp())}, {}):
        with pytest.raises(HTTPException):
            _resolve(payload)


def test_token_issued_after_revocation_is_accepted() -> None:
    user, resolved = _resolve({"iat": int((REVOKED_AT + timedelta(minutes=5)).timestamp())})
    assert resolved is user


def test_accounts_never_revoked_and_foreign_tokens_are_unaffected() -> None:
    user, resolved = _resolve({}, valid_after=None)
    assert resolved is user
    # An identity provider's token is not this backend's to revoke.
    user, resolved = _resolve({"iss": "https://tenant.auth0.com/", "iat": 1})
    assert resolved is user
