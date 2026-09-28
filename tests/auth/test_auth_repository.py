import jose
import jwt
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from uuid import uuid4

import pytest

from pecha_api.users.users_models import Users
from pecha_api.auth.auth_repository import (
    get_hashed_password,
    verify_password,
    create_access_token,
    create_refresh_token,
    is_refresh_token_payload,
    generate_token_data,
    decode_backend_token,
    verify_auth0_token,
    _allowed_auth0_audiences,
)
from pecha_api.users.users_service import validate_token

PECHA_JWT_ISSUER = "https://pecha.org"
PECHA_JWT_AUD = "https://pecha.org"


def test_verify_password_success():
    plain_password = "mysecretpassword"
    hashed_password = get_hashed_password(plain_password)

    assert verify_password(plain_password, hashed_password) == True


def test_verify_password_fail():
    plain_password = "mysecretpassword"
    hashed_password = get_hashed_password(plain_password)

    assert verify_password("wrongpassword", hashed_password) == False
    assert verify_password("wrongpassword", "wrongpassword") == False
    assert verify_password("wrongpassword", "") == False
    assert verify_password("wrongpassword", None) == False
    assert verify_password(None, "wrongpassword") == False
    assert verify_password("", "wrongpassword") == False
    assert verify_password("", hashed_password) == False
    assert verify_password(None, hashed_password) == False
    assert verify_password(plain_password, "") == False
    assert verify_password(plain_password, None) == False
    assert verify_password("", "") == False
    assert verify_password(None, None) == False
    assert verify_password("", None) == False
    assert verify_password(None, "") == False


def test_get_hashed_password():
    plain_password = "mysecretpassword"
    hashed_password = get_hashed_password(plain_password)

    assert hashed_password != plain_password
    assert verify_password(plain_password, hashed_password) == True


def test_get_hashed_password_empty_password():
    plain_password = ""
    hashed_password = get_hashed_password(plain_password)

    assert hashed_password == None


def test_get_hashed_password_none_password():
    plain_password = None
    hashed_password = get_hashed_password(plain_password)
    assert hashed_password == None


def test_get_hashed_password_different_passwords():
    plain_password1 = "mysecretpassword"
    plain_password2 = "anotherpassword"
    hashed_password1 = get_hashed_password(plain_password1)
    hashed_password2 = get_hashed_password(plain_password2)

    assert hashed_password1 != hashed_password2
    assert verify_password(plain_password1, hashed_password1) == True
    assert verify_password(plain_password2, hashed_password2) == True
    assert verify_password(plain_password1, hashed_password2) == False
    assert verify_password(plain_password2, hashed_password1) == False


def test_verify_password_with_valid_password():
    plain_password = "validpassword"
    hashed_password = get_hashed_password(plain_password)

    assert verify_password(plain_password, hashed_password) == True


def test_verify_password_with_invalid():
    plain_password = "validpassword"
    hashed_password = get_hashed_password(plain_password)

    assert verify_password("", hashed_password) == False
    assert verify_password("invalidpassword", hashed_password) == False
    assert verify_password(None, hashed_password) == False
    assert verify_password(plain_password, "") == False
    assert verify_password(plain_password, None) == False
    assert verify_password("", "") == False
    assert verify_password(None, None) == False
    assert verify_password("", None) == False
    assert verify_password(None, "") == False


def test_create_access_token():
    data = {
        "email": "test@example.com",
        "name": "John Doe",
        "iss": PECHA_JWT_ISSUER,
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }
    token = create_access_token(data)

    assert token is not None
    decoded_data = validate_token(token)
    assert decoded_data["email"] == "test@example.com"
    assert "exp" in decoded_data


def test_create_access_token_with_custom_expiry():
    data = {
        "email": "test@example.com",
        "name": "John Doe ",
        "iss": PECHA_JWT_ISSUER,
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }
    expires_delta = timedelta(minutes=10)
    token = create_access_token(data, expires_delta)

    assert token is not None
    decoded_data = validate_token(token)
    assert decoded_data["email"] == "test@example.com"
    assert "exp" in decoded_data
    assert decoded_data["exp"] == int((datetime.now(timezone.utc) + expires_delta).timestamp())



def test_create_refresh_token():
    data = {
        "email": "test@example.com",
        "name": "John Doe ",
        "iss": PECHA_JWT_ISSUER,
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }
    token = create_refresh_token(data)

    assert token is not None
    decoded_data = validate_token(token)
    assert decoded_data["email"] == "test@example.com"
    assert "exp" in decoded_data


def test_create_refresh_token_with_custom_expiry():
    data = {
        "email": "test@example.com",
        "name": "John Doe ",
        "iss": PECHA_JWT_ISSUER,
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }
    expires_delta = timedelta(days=10)
    token = create_refresh_token(data, expires_delta)

    assert token is not None
    decoded_data = validate_token(token)
    assert decoded_data["email"] == "test@example.com"
    assert "exp" in decoded_data
    assert decoded_data["exp"] == int((datetime.now(timezone.utc) + expires_delta).timestamp())



def test_refresh_token_is_distinguishable_from_access_token():
    """Both tokens carry the same claims, so the refresh token is marked - that
    marker is what keeps it from being replayed as a bearer access token."""
    data = {
        "email": "test@example.com",
        "name": "John Doe ",
        "iss": PECHA_JWT_ISSUER,
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }

    refresh_payload = validate_token(create_refresh_token(data))
    access_payload = validate_token(create_access_token(data))

    assert refresh_payload["token_type"] == "refresh"
    assert "token_type" not in access_payload
    assert is_refresh_token_payload(refresh_payload) is True
    assert is_refresh_token_payload(access_payload) is False


def test_generate_token_data_success():
    user_id = uuid4()
    user = Users(
        id=user_id,
        email="test@example.com",
        firstname="John",
        lastname="Doe",
        registration_source="email"
    )
    token_data = generate_token_data(user)

    assert token_data is not None
    assert token_data["sub"] == str(user_id)
    assert token_data["email"] == "test@example.com"
    assert token_data["name"] == "John Doe"
    assert token_data["iss"] == PECHA_JWT_ISSUER
    assert token_data["aud"] == PECHA_JWT_AUD
    assert "iat" in token_data


def test_generate_token_data_missing_email():
    user_id = uuid4()
    user = Users(
        id=user_id,
        email="test@example.com",
        firstname="John",
        lastname="Doe",
        registration_source="email"
    )
    user.email = None
    token_data = generate_token_data(user)

    assert token_data is not None
    assert token_data["sub"] == str(user_id)
    assert "email" not in token_data


def test_generate_token_data_missing_firstname():
    user = Users(
        id=uuid4(),
        email="test@example.com",
        firstname="John",
        lastname="Doe",
        registration_source="email"
    )
    user.firstname = None
    token_data = generate_token_data(user)

    assert token_data is None


def test_generate_token_data_missing_lastname():
    user = Users(
        id=uuid4(),
        email="test@example.com",
        firstname="John",
        lastname=None,
        registration_source="email"
    )
    token_data = generate_token_data(user)

    assert token_data is None


def test_generate_token_data_all_fields_missing():
    # Create a valid user first, then modify fields to None
    user = Users(
        email="test@example.com",
        firstname="John",
        lastname="Doe",
        registration_source="email"
    )
    # Simulate missing fields by setting them to None after creation
    user.email = None
    user.firstname = None
    user.lastname = None
    token_data = generate_token_data(user)

    assert token_data is None


def test_decode_token_success():
    data = {
        "email": "test@example.com",
        "name": "John Doe",
        "iss": PECHA_JWT_ISSUER,
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }
    token = create_access_token(data)
    decoded_data = validate_token(token)

    assert decoded_data is not None
    assert decoded_data["email"] == "test@example.com"
    assert decoded_data["name"] == "John Doe"
    assert decoded_data["iss"] == PECHA_JWT_ISSUER
    assert decoded_data["aud"] == PECHA_JWT_AUD
    assert "exp" in decoded_data


def test_decode_token_invalid_signature():
    data = {
        "email": "test@example.com",
        "name": "John Doe",
        "iss": PECHA_JWT_ISSUER,
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }
    token = create_access_token(data)
    invalid_token = token + "invalid"

    try:
        validate_token(invalid_token)
        assert False, "Expected jose.exceptions.JWSSignatureError"
    except jose.exceptions.JWSSignatureError:
        pass
    except jose.exceptions.JWTError:
        pass


def test_decode_token_expired():
    data = {
        "email": "test@example.com",
        "name": "John Doe",
        "iss": PECHA_JWT_ISSUER,
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }
    expires_delta = timedelta(seconds=-1)
    token = create_access_token(data, expires_delta)

    try:
        validate_token(token)
        assert False, "Expected jose.exceptions.ExpiredSignatureError"
    except jose.exceptions.ExpiredSignatureError:
        pass


def test_decode_token_invalid_audience():
    data = {
        "email": "test@example.com",
        "name": "John Doe",
        "iss": PECHA_JWT_ISSUER,
        "aud": "invalid_audience",
        "iat": datetime.now(timezone.utc)
    }
    token = create_access_token(data)
    try:
        validate_token(token)
        assert False, "Expected jwt.exceptions.InvalidAudienceError"
    except jose.exceptions.JWTClaimsError:
        pass


def test_decode_token_invalid_issuer():
    data = {
        "email": "test@example.com",
        "name": "John Doe",
        "iss": "invalid_issuer",
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }
    token = create_access_token(data)

    try:
        validate_token(token)
    except jwt.exceptions.InvalidIssuerError:
        assert False, "Expected jwt.exceptions.InvalidIssuerError"


def test_decode_backend_token_success():
    data = {
        "email": "test@example.com",
        "name": "John Doe",
        "iss": PECHA_JWT_ISSUER,
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }
    token = create_access_token(data)
    decoded_data = decode_backend_token(token)

    assert decoded_data is not None
    assert decoded_data["email"] == "test@example.com"
    assert decoded_data["name"] == "John Doe"
    assert decoded_data["iss"] == PECHA_JWT_ISSUER
    assert decoded_data["aud"] == PECHA_JWT_AUD
    assert "exp" in decoded_data


def test_decode_backend_token_invalid_signature():
    data = {
        "email": "test@example.com",
        "name": "John Doe",
        "iss": PECHA_JWT_ISSUER,
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }
    token = create_access_token(data)
    invalid_token = token + "invalid"

    try:
        decode_backend_token(invalid_token)
        assert False, "Expected jose.exceptions.JWSSignatureError"
    except jose.exceptions.JWSSignatureError:
        pass
    except jose.exceptions.JWTError:
        pass


def test_decode_backend_token_expired():
    data = {
        "email": "test@example.com",
        "name": "John Doe",
        "iss": PECHA_JWT_ISSUER,
        "aud": PECHA_JWT_AUD,
        "iat": datetime.now(timezone.utc)
    }
    expires_delta = timedelta(seconds=-1)
    token = create_access_token(data, expires_delta)

    try:
        decode_backend_token(token)
        assert False, "Expected jose.exceptions.ExpiredSignatureError"
    except jose.exceptions.ExpiredSignatureError:
        pass


def test_verify_auth0_token_exposes_verified_phone_number_for_sms_logins():
    auth0_payload = {
        "sub": "sms|6a744811b6f40222b44b0bf3",
        "aud": "webuddhist-backend",
        "https://webuddhist.com/phone_number": "+1 (415) 555-2671",
        "https://webuddhist.com/phone_number_verified": True,
    }
    with patch(
        "pecha_api.auth.auth_repository.get_auth0_public_key",
        return_value={"key-1": {"kid": "key-1"}},
    ), patch(
        "pecha_api.auth.auth_repository.jwt.get_unverified_header",
        return_value={"kid": "key-1"},
    ), patch(
        "pecha_api.auth.auth_repository.jwt.decode",
        return_value=auth0_payload,
    ), patch(
        "pecha_api.auth.auth_repository._allowed_auth0_audiences",
        return_value=["webuddhist-backend"],
    ):
        payload = verify_auth0_token("token")

    assert payload["phone_number"] == "+14155552671"
    assert "email" not in payload


def test_decode_backend_token_invalid_audience():
    data = {
        "email": "test@example.com",
        "name": "John Doe",
        "iss": PECHA_JWT_ISSUER,
        "aud": "invalid_audience",
        "iat": datetime.now(timezone.utc)
    }
    token = create_access_token(data)
    try:
        decode_backend_token(token)
        assert False, "Expected jwt.exceptions.InvalidAudienceError"
    except jose.exceptions.JWTClaimsError:
        pass
