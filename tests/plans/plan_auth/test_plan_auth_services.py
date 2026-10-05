from pecha_api.plans.response_message import EMAIL_VERIFIED_ACTIVE
from uuid import uuid4
from pecha_api.plans.auth.studio_access_service import StudioAdmission
import uuid
import json
import pytest
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime, timezone, timedelta

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette import status
from jose import jwt

from pecha_api.plans.auth.plan_auth_services import (
    register_author,
    _validate_password,
    _generate_author_verification_token,
    verify_author_email,
    request_reset_password,
    update_password,
    authenticate_author,
    check_verified_author,
    authenticate_and_generate_tokens,
    generate_token_author,
    generate_author_token_data,
    re_verify_email,
    refresh_access_token,
)
from pecha_api.plans.auth.plan_auth_models import CreateAuthorRequest, AuthorVerificationResponse, AuthorInfo, TokenResponse, AuthorLoginResponse
from pecha_api.plans.response_message import (
    PASSWORD_EMPTY,
    PASSWORD_LENGTH_INVALID,
    TOKEN_EXPIRED,
    EMAIL_ALREADY_VERIFIED,
    EMAIL_VERIFIED_SUCCESS,
    REGISTRATION_MESSAGE, TOKEN_INVALID,
    BAD_REQUEST,
    AUTHOR_ALREADY_EXISTS,
    AUTHOR_NOT_FOUND,
    EMAIL_IS_SENT,
)
from pecha_api.plans.auth.plan_auth_enums import AuthorStatus


def _mock_session_local(mock_session_local):
    mock_db_session = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db_session
    mock_session_local.return_value.__exit__.return_value = False
    return mock_db_session


def test_register_author_success():
    create_request = CreateAuthorRequest(
        first_name="John",
        last_name="Doe",
        email="john.doe@example.com",
        password="password123",
    )

    saved_author = MagicMock()
    saved_author.id = uuid.uuid4()
    saved_author.first_name = create_request.first_name
    saved_author.last_name = create_request.last_name
    saved_author.email = create_request.email
    saved_author.status = AuthorStatus.PENDING_VERIFICATION
    saved_author.is_verified = False
    saved_author.created_at = datetime.now(timezone.utc)
    saved_author.created_by = create_request.email

    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.auth.plan_auth_services.save_author") as mock_save_author, \
        patch("pecha_api.plans.auth.plan_auth_services.get_hashed_password") as mock_get_hashed_password, \
        patch("pecha_api.plans.auth.plan_auth_services._send_verification_email") as mock_send_email, \
        patch("pecha_api.plans.auth.plan_auth_services.check_author_exists", return_value=False) as mock_check_exists, \
        patch("pecha_api.plans.auth.plan_auth_services._validate_password") as mock_validate_password:
        _mock_session_local(mock_session_local)

        mock_save_author.return_value = saved_author
        mock_get_hashed_password.return_value = "hashed_password123"

        response = register_author(create_user_request=create_request)

        mock_get_hashed_password.assert_called_once()
        mock_save_author.assert_called_once()
        mock_send_email.assert_called_once()
        mock_check_exists.assert_called_once()

        assert response is not None
        assert response.first_name == saved_author.first_name
        assert response.last_name == saved_author.last_name
        assert response.email == saved_author.email
        assert response.status == AuthorStatus.PENDING_VERIFICATION
        assert response.message == REGISTRATION_MESSAGE


def test_register_author_duplicate_raises_400():
    create_request = CreateAuthorRequest(
        first_name="John",
        last_name="Doe",
        email="john.doe@example.com",
        password="password123",
    )

    saved_author = MagicMock()
    saved_author.id = uuid.uuid4()
    saved_author.first_name = create_request.first_name
    saved_author.last_name = create_request.last_name
    saved_author.email = create_request.email
    saved_author.status = AuthorStatus.PENDING_VERIFICATION
    saved_author.is_verified = False
    saved_author.created_at = datetime.now(timezone.utc)
    saved_author.created_by = create_request.email

    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.auth.plan_auth_services.check_author_exists") as mock_check_exists, \
        patch("pecha_api.plans.auth.plan_auth_services.save_author") as mock_save_author, \
        patch("pecha_api.plans.auth.plan_auth_services.get_hashed_password") as mock_get_hashed_password, \
        patch("pecha_api.plans.auth.plan_auth_services._send_verification_email") as mock_send_email:
        _mock_session_local(mock_session_local)

        mock_check_exists.side_effect = HTTPException(status_code=400, detail={"error": BAD_REQUEST, "message": AUTHOR_ALREADY_EXISTS})

        try:
            register_author(create_user_request=create_request)
            assert False, "Expected HTTPException to be raised"
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == {"error": BAD_REQUEST, "message": AUTHOR_ALREADY_EXISTS}

        mock_save_author.assert_not_called()
        mock_get_hashed_password.assert_not_called()
        mock_send_email.assert_not_called()


@pytest.mark.parametrize("password,expected_error,test_description", [
    ("", PASSWORD_EMPTY, "empty_password"),
    ("short", PASSWORD_LENGTH_INVALID, "short_password"),
])
def test__validate_password_invalid_cases(password, expected_error, test_description):
    with pytest.raises(HTTPException) as exc_info:
        _validate_password(password)
    
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert exc_info.value.detail == expected_error


def test__validate_password_valid():
    _validate_password("validpass")


def test__generate_author_verification_token_and_decode():
    email = "john.doe@example.com"

    def fake_get(key: str):
        mapping = {
            "JWT_ISSUER": "pecha",
            "JWT_AUD": "pecha-users",
            "JWT_SECRET_KEY": "secret-key",
            "JWT_ALGORITHM": "HS256",
        }
        return mapping[key]

    with patch("pecha_api.plans.auth.plan_auth_services.get", side_effect=fake_get):
        token = _generate_author_verification_token(email)
        assert isinstance(token, str) and len(token) > 0

        payload = jwt.decode(
            token,
            fake_get("JWT_SECRET_KEY"),
            algorithms=[fake_get("JWT_ALGORITHM")],
            audience=fake_get("JWT_AUD"),
        )
        assert payload["email"] == email
        assert payload["iss"] == fake_get("JWT_ISSUER")
        assert payload["aud"] == fake_get("JWT_AUD")
        assert payload["typ"] == "author_email_verification"
        assert datetime.fromtimestamp(payload["exp"], tz=timezone.utc) > datetime.now(timezone.utc)


def test_verify_author_email_success(_no_studio_admission):
    token = "valid_token"
    payload = {
        "email": "john.doe@example.com",
        "typ": "author_email_verification",
    }

    author = MagicMock()
    author.is_verified = False
    author.is_active = False
    author.suspended_at = None
    author.email = "john.doe@example.com"

    with patch("pecha_api.plans.auth.plan_auth_services.get", return_value="x"), \
        patch("pecha_api.plans.auth.plan_auth_services.jwt.decode", return_value=payload) as mock_decode, \
        patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email") as mock_get_author_by_email, \
        patch("pecha_api.plans.auth.plan_auth_services.update_author") as mock_update_author, \
        patch("pecha_api.plans.auth.plan_auth_services.notify_pending_group_invites") as mock_notify:
        _mock_session_local(mock_session_local)
        mock_get_author_by_email.return_value = author

        def _admit(db, admitted, join_link_token=None):
            admitted.is_active = True
            return StudioAdmission()

        _no_studio_admission.side_effect = _admit
        response: AuthorVerificationResponse = verify_author_email(token)

        mock_decode.assert_called_once()
        mock_get_author_by_email.assert_called_once_with(db=ANY, email=payload["email"])
        mock_update_author.assert_called_once_with(db=ANY, author=author)
        mock_notify.assert_called_once_with(author)
        assert response.email == "john.doe@example.com"
        assert response.status == AuthorStatus.ACTIVE
        assert response.account_status == AuthorStatus.ACTIVE
        assert response.message == EMAIL_VERIFIED_ACTIVE


def test_verify_author_email_already_verified():
    token = "valid_token"
    payload = {
        "email": "john.doe@example.com",
        "typ": "author_email_verification",
    }

    author = MagicMock()
    author.is_verified = True
    author.is_active = False
    author.suspended_at = None
    author.email = "john.doe@example.com"

    with patch("pecha_api.plans.auth.plan_auth_services.get", return_value="x"), \
        patch("pecha_api.plans.auth.plan_auth_services.jwt.decode", return_value=payload), \
        patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email") as mock_get_author_by_email, \
        patch("pecha_api.plans.auth.plan_auth_services.update_author") as mock_update_author, \
        patch("pecha_api.plans.auth.plan_auth_services.notify_pending_group_invites") as mock_notify:
        _mock_session_local(mock_session_local)
        mock_get_author_by_email.return_value = author

        response: AuthorVerificationResponse  = verify_author_email(token)

        mock_update_author.assert_not_called()
        mock_notify.assert_not_called()
        assert response.email == "john.doe@example.com"
        assert response.status == AuthorStatus.INACTIVE
        assert response.message == EMAIL_ALREADY_VERIFIED


def test_verify_author_email_invalid_type():
    token = "valid_token"
    payload = {
        "email": "john.doe@example.com",
        "typ": "wrong_type",
    }

    with patch("pecha_api.plans.auth.plan_auth_services.get", return_value="x"), \
        patch("pecha_api.plans.auth.plan_auth_services.jwt.decode", return_value=payload):
        try:
            verify_author_email(token)
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == TOKEN_INVALID


def test_verify_author_email_missing_email():
    token = "valid_token"
    payload = {
        "typ": "author_email_verification",
    }

    with patch("pecha_api.plans.auth.plan_auth_services.get", return_value="x"), \
        patch("pecha_api.plans.auth.plan_auth_services.jwt.decode", return_value=payload):
        try:
            verify_author_email(token)
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == TOKEN_INVALID


def test_verify_author_email_expired_token():
    token = "expired_token"

    with patch("pecha_api.plans.auth.plan_auth_services.get", return_value="x"), \
        patch("pecha_api.plans.auth.plan_auth_services.jwt.decode") as mock_decode:
        mock_decode.side_effect = jwt.ExpiredSignatureError

        try:
            verify_author_email(token)
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == TOKEN_EXPIRED



def test_send_verification_email_sends_email():
    from pecha_api.plans.auth.plan_auth_services import _send_verification_email

    with patch("pecha_api.plans.auth.plan_auth_services._generate_author_verification_token", return_value="tok"), \
        patch("pecha_api.plans.auth.plan_auth_services.get", side_effect=lambda k: "http://frontend" if k == "WEBUDDHIST_STUDIO_BASE_URL" else "x"), \
        patch("pecha_api.plans.auth.plan_auth_services.Template.render") as mock_render, \
        patch("pecha_api.plans.auth.plan_auth_services.send_email") as mock_send_email:
        mock_render.return_value = "rendered_html"

        _send_verification_email("john.doe@example.com")

        mock_render.assert_called_once()
        mock_send_email.assert_called_once_with(
            to_email="john.doe@example.com",
            subject="Verify your Pecha account",
            message="rendered_html",
        )




def test_authenticate_author_success():
    author = MagicMock()
    author.password = "hashed"
    author.is_verified = True
    author.is_active = True

    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email", return_value=author), \
        patch("pecha_api.plans.auth.plan_auth_services.verify_password", return_value=True):
        _mock_session_local(mock_session_local)

        result_author, admission = authenticate_author("test@example.com", "password")
        assert result_author == author
        assert admission.joined_group_ids == []


def test_authenticate_author_invalid_password():
    author = MagicMock()
    author.password = "hashed"
    author.is_verified = True
    author.is_active = True

    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
        patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email", return_value=author), \
        patch("pecha_api.plans.auth.plan_auth_services.verify_password", return_value=False):
        _mock_session_local(mock_session_local)

        try:
            authenticate_author("test@example.com", "wrong")
        except HTTPException as e:
            assert e.status_code == status.HTTP_401_UNAUTHORIZED
            assert e.detail == "Invalid email or password"


def test_check_verified_author_not_verified():
    author = MagicMock(is_verified=False, is_active=True)
    try:
        check_verified_author(author)
    except HTTPException as e:
        assert e.status_code == status.HTTP_401_UNAUTHORIZED
        assert e.detail == "Author not verified"


def test_check_verified_author_not_active():
    author = MagicMock(is_verified=True, is_active=False)
    try:
        check_verified_author(author)
    except HTTPException as e:
        assert e.status_code == status.HTTP_401_UNAUTHORIZED
        assert e.detail == "Author not active"


def test_check_verified_author_valid():
    author = MagicMock(is_verified=True, is_active=True)
    check_verified_author(author)


def test_authenticate_and_generate_tokens():
    author = MagicMock()
    group_id = uuid4()
    admission = StudioAdmission(joined_group_ids=[group_id], join_link_error="expired")
    tokens = MagicMock()
    with patch("pecha_api.plans.auth.plan_auth_services.authenticate_author", return_value=(author, admission)), \
        patch("pecha_api.plans.auth.plan_auth_services.generate_token_author", return_value=tokens) as mock_gen:
        result = authenticate_and_generate_tokens("email", "password")
        mock_gen.assert_called_once_with(author)
        assert result is tokens
        assert result.joined_group_ids == [group_id]
        assert result.join_link_error == "expired"


def test_generate_token_author_builds_response():
    author = MagicMock()
    author.first_name = "John"
    author.last_name = "Doe"
    author.email = "john.doe@example.com"
    author.image_url = "img.png"

    with patch("pecha_api.plans.auth.plan_auth_services.generate_author_token_data", return_value={"sub": "123"}), \
        patch("pecha_api.plans.auth.plan_auth_services.create_access_token", return_value="access"), \
        patch("pecha_api.plans.auth.plan_auth_services.create_refresh_token", return_value="refresh"):
        result = generate_token_author(author)

        assert isinstance(result, AuthorLoginResponse)
        assert isinstance(result.user, AuthorInfo)
        assert isinstance(result.auth, TokenResponse)
        assert result.auth.access_token == "access"
        assert result.auth.refresh_token == "refresh"
        assert result.user.name == "John Doe"
        assert result.user.image_url == "img.png"

def test_generate_token_author_uses_studio_token_lifetimes():
    """Studio sessions last two days and renew for a month; the app's shared
    ACCESS_TOKEN_EXPIRE_MINUTES / REFRESH_TOKEN_EXPIRE_DAYS are untouched."""
    author = MagicMock()
    author.first_name = "John"
    author.last_name = "Doe"
    author.email = "john.doe@example.com"
    author.image_url = "img.png"

    with patch("pecha_api.plans.auth.plan_auth_services.generate_author_token_data", return_value={"sub": "123"}),         patch("pecha_api.plans.auth.plan_auth_services.create_access_token", return_value="access") as mock_access,         patch("pecha_api.plans.auth.plan_auth_services.create_refresh_token", return_value="refresh") as mock_refresh:
        generate_token_author(author)

        assert mock_access.call_args.kwargs["expires_delta"] == timedelta(days=2)
        assert mock_refresh.call_args.kwargs["expires_delta"] == timedelta(days=30)


def test_refresh_access_token_uses_studio_access_lifetime():
    payload = {"sub": "123"}
    with patch("pecha_api.plans.auth.plan_auth_services._validate_token", return_value=payload),         patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local,         patch("pecha_api.plans.auth.plan_auth_services.resolve_author_from_backend_payload", return_value=MagicMock()),         patch("pecha_api.plans.auth.plan_auth_services.generate_author_token_data", return_value=payload),         patch("pecha_api.plans.auth.plan_auth_services.create_access_token", return_value="access") as mock_access:
        _mock_session_local(mock_session_local)

        result = refresh_access_token("refresh-token")

        assert result.access_token == "access"
        assert mock_access.call_args.kwargs["expires_delta"] == timedelta(days=2)


def test_request_reset_password_success():
    email = "john.doe@example.com"
    
    mock_author = MagicMock()
    mock_author.email = email
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email", return_value=mock_author) as mock_get_author, \
         patch("pecha_api.plans.auth.plan_auth_services.save_password_reset") as mock_save_reset, \
         patch("pecha_api.plans.auth.plan_auth_services.send_reset_email") as mock_send_email, \
         patch("pecha_api.plans.auth.plan_auth_services.secrets.token_urlsafe", return_value="test_token_123"), \
         patch("pecha_api.plans.auth.plan_auth_services.get", return_value="https://example.com"):
        
        mock_db_session = _mock_session_local(mock_session_local)
        
        result = request_reset_password(email=email)
        
        mock_get_author.assert_called_once_with(db=mock_db_session, email=email)
        mock_save_reset.assert_called_once()
        mock_send_email.assert_called_once_with(
            email=email, 
            reset_link="https://example.com/reset-password?token=test_token_123&email=john.doe@example.com"
        )
        
        assert result == {"message": "If the email exists in our system, a password reset email has been sent."}


def test_request_reset_password_author_not_found():
    email = "nonexistent@example.com"
    
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email") as mock_get_author:
        
        _mock_session_local(mock_session_local)
        mock_get_author.side_effect = HTTPException(status_code=404, detail="Author not found")
        
        try:
            request_reset_password(email=email)
            assert False, "Expected HTTPException to be raised"
        except HTTPException as e:
            assert e.status_code == 404
            assert e.detail == "Author not found"


def test_request_reset_password_database_error():
    email = "john.doe@example.com"
    
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email") as mock_get_author:
        
        _mock_session_local(mock_session_local)
        mock_get_author.side_effect = Exception("Database connection error")
        
        try:
            request_reset_password(email=email)
            assert False, "Expected Exception to be raised"
        except Exception as e:
            assert str(e) == "Database connection error"


def test_request_reset_password_email_send_failure():
    email = "john.doe@example.com"
    
    mock_author = MagicMock()
    mock_author.email = email
    
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email", return_value=mock_author), \
         patch("pecha_api.plans.auth.plan_auth_services.save_password_reset"), \
         patch("pecha_api.plans.auth.plan_auth_services.send_reset_email") as mock_send_email, \
         patch("pecha_api.plans.auth.plan_auth_services.secrets.token_urlsafe", return_value="test_token_123"), \
         patch("pecha_api.plans.auth.plan_auth_services.get", return_value="https://example.com"):
        
        _mock_session_local(mock_session_local)
        mock_send_email.side_effect = Exception("Email service unavailable")
        
        try:
            request_reset_password(email=email)
            assert False, "Expected Exception to be raised"
        except Exception as e:
            assert str(e) == "Email service unavailable"


def test_update_password_success():
    token = "valid_reset_token"
    new_password = "newpassword123"
    email = "john.doe@example.com"
    
    mock_reset_entry = MagicMock()
    mock_reset_entry.email = email
    mock_reset_entry.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)  # Valid expiry
    
    mock_author = MagicMock()
    mock_author.email = email
    mock_author.registration_source = 'email'
    
    mock_updated_author = MagicMock()
    mock_updated_author.email = email
    mock_updated_author.password = "hashed_new_password"
    
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_password_reset_by_token_for_author", return_value=mock_reset_entry) as mock_get_reset, \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email", return_value=mock_author) as mock_get_author, \
         patch("pecha_api.plans.auth.plan_auth_services._validate_password") as mock_validate, \
         patch("pecha_api.plans.auth.plan_auth_services.get_hashed_password", return_value="hashed_new_password") as mock_hash, \
         patch("pecha_api.plans.auth.plan_auth_services.save_author", return_value=mock_updated_author) as mock_save:
        
        mock_db_session = _mock_session_local(mock_session_local)
        
        result = update_password(token=token, password=new_password)
        
        mock_get_reset.assert_called_once_with(db=mock_db_session, token=token)
        mock_get_author.assert_called_once_with(db=mock_db_session, email=email)
        mock_validate.assert_called_once_with(new_password)
        mock_hash.assert_called_once_with(new_password)
        mock_save.assert_called_once_with(db=mock_db_session, author=mock_author)
        
        assert mock_author.password == "hashed_new_password"
        assert result == mock_updated_author


def test_update_password_invalid_token():
    token = "invalid_token"
    new_password = "newpassword123"
    
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_password_reset_by_token_for_author", return_value=None) as mock_get_reset:
        
        _mock_session_local(mock_session_local)
        
        try:
            update_password(token=token, password=new_password)
            assert False, "Expected HTTPException to be raised"
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == "Invalid or expired token"


def test_update_password_expired_token():
    token = "expired_token"
    new_password = "newpassword123"
    
    mock_reset_entry = MagicMock()
    mock_reset_entry.email = "john.doe@example.com"
    mock_reset_entry.token_expiry = datetime.now(timezone.utc) - timedelta(minutes=10)
    
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_password_reset_by_token_for_author", return_value=mock_reset_entry):
        
        _mock_session_local(mock_session_local)
        
        try:
            update_password(token=token, password=new_password)
            assert False, "Expected HTTPException to be raised"
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == "Invalid or expired token"


def test_update_password_oauth_user_success():
    """Test that OAuth users (Google, Facebook, etc.) can successfully reset passwords.
    Registration source validation was removed to allow all users to set passwords."""
    token = "valid_reset_token"
    new_password = "newpassword123"
    email = "john.doe@example.com"
    
    mock_reset_entry = MagicMock()
    mock_reset_entry.email = email
    mock_reset_entry.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    
    mock_author = MagicMock()
    mock_author.email = email
    mock_author.registration_source = 'google'  # OAuth user
    
    mock_updated_author = MagicMock()
    mock_updated_author.email = email
    mock_updated_author.password = "hashed_new_password"
    
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_password_reset_by_token_for_author", return_value=mock_reset_entry) as mock_get_reset, \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email", return_value=mock_author) as mock_get_author, \
         patch("pecha_api.plans.auth.plan_auth_services._validate_password") as mock_validate, \
         patch("pecha_api.plans.auth.plan_auth_services.get_hashed_password", return_value="hashed_new_password") as mock_hash, \
         patch("pecha_api.plans.auth.plan_auth_services.save_author", return_value=mock_updated_author) as mock_save:
        
        mock_db_session = _mock_session_local(mock_session_local)
        
        result = update_password(token=token, password=new_password)
        
        mock_get_reset.assert_called_once_with(db=mock_db_session, token=token)
        mock_get_author.assert_called_once_with(db=mock_db_session, email=email)
        mock_validate.assert_called_once_with(new_password)
        mock_hash.assert_called_once_with(new_password)
        mock_save.assert_called_once_with(db=mock_db_session, author=mock_author)
        
        assert mock_author.password == "hashed_new_password"
        assert result == mock_updated_author


def test_update_password_weak_password():
    token = "valid_reset_token"
    new_password = "weak"  
    email = "john.doe@example.com"
    
    mock_reset_entry = MagicMock()
    mock_reset_entry.email = email
    mock_reset_entry.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    
    mock_author = MagicMock()
    mock_author.email = email
    mock_author.registration_source = 'email'
    
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_password_reset_by_token_for_author", return_value=mock_reset_entry), \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email", return_value=mock_author), \
         patch("pecha_api.plans.auth.plan_auth_services._validate_password") as mock_validate:
        
        _mock_session_local(mock_session_local)
        mock_validate.side_effect = HTTPException(status_code=400, detail="Password must be between 8 and 20 characters")
        
        try:
            update_password(token=token, password=new_password)
            assert False, "Expected HTTPException to be raised"
        except HTTPException as e:
            assert e.status_code == 400
            assert e.detail == "Password must be between 8 and 20 characters"


def test_update_password_author_not_found():
    token = "valid_reset_token"
    new_password = "newpassword123"
    email = "nonexistent@example.com"
    
    mock_reset_entry = MagicMock()
    mock_reset_entry.email = email
    mock_reset_entry.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_password_reset_by_token_for_author", return_value=mock_reset_entry), \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email") as mock_get_author:
        
        _mock_session_local(mock_session_local)
        mock_get_author.side_effect = HTTPException(status_code=404, detail="Author not found")
        
        try:
            update_password(token=token, password=new_password)
            assert False, "Expected HTTPException to be raised"
        except HTTPException as e:
            assert e.status_code == 404
            assert e.detail == "Author not found"


def test_update_password_database_save_error():
    token = "valid_reset_token"
    new_password = "newpassword123"
    email = "john.doe@example.com"
    
    mock_reset_entry = MagicMock()
    mock_reset_entry.email = email
    mock_reset_entry.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=10)
    
    mock_author = MagicMock()
    mock_author.email = email
    mock_author.registration_source = 'email'
    
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_password_reset_by_token_for_author", return_value=mock_reset_entry), \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email", return_value=mock_author), \
         patch("pecha_api.plans.auth.plan_auth_services._validate_password"), \
         patch("pecha_api.plans.auth.plan_auth_services.get_hashed_password", return_value="hashed_password"), \
         patch("pecha_api.plans.auth.plan_auth_services.save_author") as mock_save:
        
        _mock_session_local(mock_session_local)
        mock_save.side_effect = Exception("Database save failed")
        
        try:
            update_password(token=token, password=new_password)
            assert False, "Expected Exception to be raised"
        except Exception as e:
            assert str(e) == "Database save failed"


def test_generate_author_token_data_success():
    author = MagicMock()
    author.email = "john.doe@example.com"
    author.first_name = "John"
    author.last_name = "Doe"
    
    with patch("pecha_api.plans.auth.plan_auth_services.get") as mock_get, \
         patch("pecha_api.plans.auth.plan_auth_services.datetime") as mock_datetime:
        
        mock_get.side_effect = lambda key: {
            "JWT_ISSUER": "https://pecha.org",
            "JWT_AUD": "https://pecha.org"
        }[key]
        
        mock_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.timezone = timezone
        
        result = generate_author_token_data(author)
        
        assert result is not None
        assert result["email"] == "john.doe@example.com"
        assert result["name"] == "John Doe"
        assert result["iss"] == "https://pecha.org"
        assert result["aud"] == "https://pecha.org"
        assert result["iat"] == mock_now


@pytest.mark.parametrize("email,first_name,last_name,test_description", [
    ("john.doe@example.com", None, "Doe", "missing_first_name"),
    ("john.doe@example.com", "", "Doe", "empty_first_name"),
    ("john.doe@example.com", "John", None, "missing_last_name"),
    ("john.doe@example.com", "John", "", "empty_last_name"),
    (None, None, None, "all_fields_missing"),
])
def test_generate_author_token_data_invalid_inputs(email, first_name, last_name, test_description):
    """Test that generate_author_token_data returns None for invalid inputs"""
    author = MagicMock()
    author.email = email
    author.first_name = first_name
    author.last_name = last_name
    
    result = generate_author_token_data(author)
    
    assert result is None


def test_generate_author_token_data_with_whitespace_names():
    author = MagicMock()
    author.email = "john.doe@example.com"
    author.first_name = " John "
    author.last_name = " Doe "
    
    with patch("pecha_api.plans.auth.plan_auth_services.get") as mock_get, \
         patch("pecha_api.plans.auth.plan_auth_services.datetime") as mock_datetime:
        
        mock_get.side_effect = lambda key: {
            "JWT_ISSUER": "https://pecha.org",
            "JWT_AUD": "https://pecha.org"
        }[key]
        
        mock_now = datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
        mock_datetime.now.return_value = mock_now
        mock_datetime.timezone = timezone
        
        result = generate_author_token_data(author)
        
        assert result is not None
        assert result["name"] == " John   Doe "
        assert result["email"] == "john.doe@example.com"


def test_re_verify_email_success():
    email = "john.doe@example.com"
    mock_author = MagicMock()
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email", return_value=mock_author) as mock_get_author, \
         patch("pecha_api.plans.auth.plan_auth_services._send_verification_email") as mock_send_verification:
        _mock_session_local(mock_session_local)

        response = re_verify_email(email=email)

        mock_get_author.assert_called_once_with(db=ANY, email=email)
        mock_send_verification.assert_called_once_with(email=email)
        assert response.message == EMAIL_IS_SENT


def test_re_verify_email_author_not_found():
    email = "noone@example.com"
    with patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email", return_value=None):
        _mock_session_local(mock_session_local)

        try:
            re_verify_email(email=email)
            assert False, "Expected HTTPException to be raised"
        except HTTPException as e:
            assert e.status_code == status.HTTP_404_NOT_FOUND
            assert e.detail == {"error": BAD_REQUEST, "message": AUTHOR_NOT_FOUND}


def test_refresh_access_token_success():
    refresh_token = "refresh123"

    payload = {"email": "john.doe@example.com"}
    author = MagicMock()
    author.first_name = "John"
    author.last_name = "Doe"
    author.email = "john.doe@example.com"

    with patch("pecha_api.plans.auth.plan_auth_services._validate_token", return_value=payload) as mock_validate, \
         patch("pecha_api.plans.auth.plan_auth_services.SessionLocal") as mock_session_local, \
         patch("pecha_api.plans.auth.plan_auth_services.get_author_by_email", return_value=author) as mock_get_author, \
         patch("pecha_api.plans.auth.plan_auth_services.generate_author_token_data", return_value={"email": "john.doe@example.com"}) as mock_token_data, \
         patch("pecha_api.plans.auth.plan_auth_services.create_access_token", return_value="new_access") as mock_create_access:

        _mock_session_local(mock_session_local)

        resp = refresh_access_token(refresh_token)

        mock_validate.assert_called_once_with(refresh_token)
        mock_get_author.assert_called_once()
        mock_token_data.assert_called_once()
        mock_create_access.assert_called_once()

        assert resp.access_token == "new_access"
        assert resp.token_type == "Bearer"


def test_refresh_access_token_missing_email_401():
    with patch("pecha_api.plans.auth.plan_auth_services._validate_token", return_value={}) as mock_validate:
        try:
            refresh_access_token("tok")
            assert False, "Expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 401
            assert e.detail == "Invalid refresh token"


def test_refresh_access_token_expired_signature_401():
    from jose import jwt as jose_jwt
    with patch("pecha_api.plans.auth.plan_auth_services._validate_token") as mock_validate:
        mock_validate.side_effect = jose_jwt.ExpiredSignatureError
        try:
            refresh_access_token("tok")
            assert False, "Expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 401
            assert e.detail == "Refresh token expired"


def test_refresh_access_token_invalid_token_401():
    from jose import jwt as jose_jwt
    with patch("pecha_api.plans.auth.plan_auth_services._validate_token") as mock_validate:
        mock_validate.side_effect = jose_jwt.JWTError
        try:
            refresh_access_token("tok")
            assert False, "Expected HTTPException"
        except HTTPException as e:
            assert e.status_code == 401
            assert e.detail == "Invalid refresh token"