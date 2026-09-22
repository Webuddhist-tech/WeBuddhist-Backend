import uuid
import jwt
import pytest
from unittest.mock import patch, MagicMock, ANY
from datetime import datetime, timedelta, timezone
from jose import JWTError
from jose.exceptions import ExpiredSignatureError as JoseExpiredSignatureError
from starlette import status

from pecha_api.auth.auth_service import (
    register_user_with_source,
    generate_token_user,
    authenticate_user,
    get_hashed_password,
    refresh_access_token,
    create_user,
    validate_user_already_exist,
    authenticate_and_generate_tokens,
    request_reset_password,
    update_password,
    send_reset_email,
    _validate_password,
    validate_username,
    generate_username,
    generate_and_validate_username,
    retrieve_client_info
)
from pecha_api.auth.auth_models import CreateUserRequest
from pecha_api.auth.auth_enums import RegistrationSource
from fastapi import HTTPException


def test_register_user_with_email_success():
    create_user_request = CreateUserRequest(
        firstname="John",
        lastname="Doe",
        email="test@example.com",
        password="password123"
    )
    registration_source = RegistrationSource.EMAIL

    with patch('pecha_api.auth.auth_service.create_user') as mock_create_user, \
            patch('pecha_api.auth.auth_service.generate_token_user') as mock_generate_token_user:
        mock_user = MagicMock()
        mock_create_user.return_value = mock_user
        mock_generate_token_user.return_value = {"access_token": "fake_access_token",
                                                 "refresh_token": "fake_refresh_token"}

        response = register_user_with_source(
            create_user_request=create_user_request,
            registration_source=registration_source
        )
        assert response == {"access_token": "fake_access_token", "refresh_token": "fake_refresh_token"}


def test_register_user_with_google_success():
    create_user_request = CreateUserRequest(
        firstname="John",
        lastname="Doe",
        email="test@gmail.com",
        password="",
        platform=RegistrationSource.GOOGLE.name
    )
    registration_source = RegistrationSource.GOOGLE
    with patch('pecha_api.auth.auth_service.create_user') as mock_create_user, \
            patch('pecha_api.auth.auth_service.generate_token_user') as mock_generate_token_user:
        mock_user = MagicMock()
        mock_create_user.return_value = mock_user
        mock_generate_token_user.return_value = {"access_token": "fake_access_token",
                                                 "refresh_token": "fake_refresh_token"}

        response = register_user_with_source(create_user_request, registration_source)

        mock_create_user.assert_called_once_with(create_user_request=create_user_request,
                                                 registration_source=registration_source)
        mock_generate_token_user.assert_called_once_with(mock_user)
        assert response == {"access_token": "fake_access_token", "refresh_token": "fake_refresh_token"}


def test_register_user_with_facebook_success():
    create_user_request = CreateUserRequest(
        firstname="John",
        lastname="Doe",
        email="test@gmail.com",
        password="",
    )
    registration_source = RegistrationSource.FACEBOOK
    with patch('pecha_api.auth.auth_service.create_user') as mock_create_user, \
            patch('pecha_api.auth.auth_service.generate_token_user') as mock_generate_token_user:
        mock_user = MagicMock()
        mock_create_user.return_value = mock_user
        mock_generate_token_user.return_value = {"access_token": "fake_access_token",
                                                 "refresh_token": "fake_refresh_token"}

        response = register_user_with_source(create_user_request, registration_source)

        mock_create_user.assert_called_once_with(create_user_request=create_user_request,
                                                 registration_source=registration_source)
        mock_generate_token_user.assert_called_once_with(mock_user)
        assert response == {"access_token": "fake_access_token", "refresh_token": "fake_refresh_token"}


def test_register_user_with_source_http_exception():
    create_user_request = CreateUserRequest(
        firstname="John",
        lastname="Doe",
        email="test@example.com",
        password="password123"
    )
    registration_source = RegistrationSource.EMAIL

    with patch('pecha_api.auth.auth_service.create_user') as mock_create_user:
        mock_create_user.side_effect = HTTPException(status_code=400, detail="User already exists")
        try:
            register_user_with_source(create_user_request, registration_source)
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == 'User already exists'


def test_generate_token_user_success():
    user = MagicMock()
    user.id = 1
    user.email = "test@example.com"
    user.firstname = "John"
    user.lastname = "Doe"
    user.avatar_url = "avatar"

    with patch('pecha_api.auth.auth_service.generate_token_data') as mock_generate_token_data, \
            patch('pecha_api.auth.auth_service.create_access_token') as mock_create_access_token, \
            patch('pecha_api.auth.auth_service.create_refresh_token') as mock_create_refresh_token:
        mock_generate_token_data.return_value = {"sub": user.email}
        mock_create_access_token.return_value = "fake_access_token"
        mock_create_refresh_token.return_value = "fake_refresh_token"

        response = generate_token_user(user)

        mock_generate_token_data.assert_called_once_with(user)
        mock_create_access_token.assert_called_once_with({"sub": user.email})
        mock_create_refresh_token.assert_called_once_with({"sub": user.email})
        assert response.user.name == "John Doe"
        assert response.user.avatar_url == "avatar"
        assert response.auth.token_type == "Bearer"
        assert response.auth.access_token == "fake_access_token"
        assert response.auth.refresh_token == "fake_refresh_token"
        assert response.auth.token_type == "Bearer"


def test_generate_token_user_http_exception():
    user = MagicMock()
    user.id = uuid.UUID
    user.email = "test@example.com"
    user.username = "testuser"
    user.avatar_url = "avatar"

    with patch('pecha_api.auth.auth_service.generate_token_data') as mock_generate_token_data:
        mock_generate_token_data.side_effect = HTTPException(status_code=500, detail="Internal Server Error")

        try:
            generate_token_user(user)
        except HTTPException as e:
            assert e.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert e.detail == 'Internal Server Error'
        mock_generate_token_data.assert_called_once_with(user)


def test_authenticate_user_success():
    email = "test@example.com"
    password = "password123"
    user = MagicMock()
    user.email = email
    user.password = get_hashed_password(password)
    user.avatar_url = "avatar"

    with patch('pecha_api.auth.auth_service.get_user_by_email') as mock_get_user_by_email, \
            patch('pecha_api.auth.auth_service.verify_password') as mock_verify_password:
        mock_get_user_by_email.return_value = user
        mock_verify_password.return_value = True

        authenticated_user = authenticate_user(email, password)

        mock_get_user_by_email.assert_called_once_with(db=ANY, email=email)
        mock_verify_password.assert_called_once_with(plain_password=password, hashed_password=user.password)
        assert authenticated_user == user


def test_authenticate_user_invalid_email():
    email = "invalid@example.com"
    password = "password123"

    with patch('pecha_api.auth.auth_service.get_user_by_email') as mock_get_user_by_email:
        mock_get_user_by_email.side_effect = HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                                           detail="User not found")
        try:
            authenticate_user(email, password)
        except HTTPException as e:
            assert e.status_code == status.HTTP_404_NOT_FOUND
            assert e.detail == 'User not found'

        mock_get_user_by_email.assert_called_once_with(db=ANY, email=email)


def test_authenticate_user_invalid_password():
    email = "test@example.com"
    password = "invalidpassword"
    user = MagicMock()
    user.email = email
    user.password = get_hashed_password("correctpassword")
    user.avatar_url = "avatar"

    with patch('pecha_api.auth.auth_service.get_user_by_email') as mock_get_user_by_email, \
            patch('pecha_api.auth.auth_service.verify_password') as mock_verify_password:
        mock_get_user_by_email.return_value = user
        mock_verify_password.return_value = False

        try:
            authenticate_user(email, password)
        except HTTPException as e:
            assert e.status_code == status.HTTP_401_UNAUTHORIZED
            assert e.detail == 'Invalid email or password'


def test_refresh_access_token_success():
    refresh_token = "valid_refresh_token"
    user = MagicMock()
    user.email = "test@example.com"
    user.firstname = "firstname"
    user.lastname = "lastname"
    user.avatar_url = "avatar"

    with patch('pecha_api.auth.auth_service.validate_token') as mock_validate_token, \
            patch('pecha_api.users.user_resolution.get_user_by_email') as mock_get_user_by_email, \
            patch('pecha_api.auth.auth_service.generate_token_data') as mock_generate_token_data, \
            patch('pecha_api.auth.auth_service.create_access_token') as mock_create_access_token:
        mock_validate_token.return_value = {"email": user.email}
        mock_get_user_by_email.return_value = user
        mock_generate_token_data.return_value = {"email": user.email}
        mock_create_access_token.return_value = "new_access_token"

        response = refresh_access_token(refresh_token)

        mock_validate_token.assert_called_once_with(refresh_token)
        mock_get_user_by_email.assert_called_once_with(db=ANY, email=user.email)
        mock_generate_token_data.assert_called_once_with(user)
        assert response.access_token == "new_access_token"
        assert response.token_type == "Bearer"


def test_refresh_access_token_invalid_token():
    refresh_token = "invalid_refresh_token"

    with patch('pecha_api.auth.auth_service.validate_token') as mock_validate_token:
        mock_validate_token.side_effect = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                                        detail="Invalid refresh token")

        try:
            refresh_access_token(refresh_token)
        except HTTPException as e:
            assert e.status_code == status.HTTP_401_UNAUTHORIZED
            assert e.detail == "Invalid refresh token"

        mock_validate_token.assert_called_once_with(refresh_token)


def test_refresh_access_token_401_no_email():
    refresh_token = "valid_refresh_token"
    user = MagicMock()
    user.firstname = "firstname"
    user.lastname = "lastname"

    with patch('pecha_api.auth.auth_service.validate_token') as mock_validate_token:
        mock_validate_token.return_value = {"sub": None}
        try:
            refresh_access_token(refresh_token)
        except HTTPException as e:
            assert e.status_code == status.HTTP_401_UNAUTHORIZED
            assert e.detail == "Invalid refresh token"


def test_refresh_access_token_expired_token():
    refresh_token = "expired_refresh_token"

    with patch('pecha_api.auth.auth_service.validate_token') as mock_validate_token:
        mock_validate_token.side_effect = jwt.ExpiredSignatureError

        try:
            refresh_access_token(refresh_token)
        except HTTPException as e:
            assert e.status_code == status.HTTP_401_UNAUTHORIZED
            assert e.detail == "Refresh token expired"

        mock_validate_token.assert_called_once_with(refresh_token)


def test_refresh_access_token_expired_jose_token():
    with patch('pecha_api.auth.auth_service.validate_token', side_effect=JoseExpiredSignatureError):
        with pytest.raises(HTTPException) as exc_info:
            refresh_access_token("expired_refresh_token")

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Refresh token expired"


@pytest.mark.parametrize(
    "validation_error",
    [JWTError("malformed token"), KeyError("kid"), TypeError("bad payload"), ValueError("bad claim")],
)
def test_refresh_access_token_rejects_unusable_tokens(validation_error):
    with patch('pecha_api.auth.auth_service.validate_token', side_effect=validation_error):
        with pytest.raises(HTTPException) as exc_info:
            refresh_access_token("unusable_refresh_token")

    assert exc_info.value.status_code == status.HTTP_401_UNAUTHORIZED
    assert exc_info.value.detail == "Invalid refresh token"


def test_refresh_access_token_user_not_found():
    refresh_token = "valid_refresh_token"

    with patch('pecha_api.auth.auth_service.validate_token') as mock_validate_token, \
            patch('pecha_api.users.user_resolution.get_user_by_email') as mock_get_user_by_email:
        mock_validate_token.return_value = {"email": "test@example.com"}
        mock_get_user_by_email.side_effect = HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                                           detail="User not found")

        try:
            refresh_access_token(refresh_token)
        except HTTPException as e:
            assert e.status_code == status.HTTP_404_NOT_FOUND
            assert e.detail == "User not found"

        mock_validate_token.assert_called_once_with(refresh_token)
        mock_get_user_by_email.assert_called_once_with(db=ANY, email="test@example.com")


def test_create_user_with_email_success():
    create_user_request = CreateUserRequest(
        firstname="John",
        lastname="Doe",
        email="test@example.com",
        password="password123"
    )
    registration_source = RegistrationSource.EMAIL

    with patch('pecha_api.auth.auth_service.save_user') as mock_save_user, \
            patch('pecha_api.auth.auth_service.get_hashed_password') as mock_get_hashed_password, \
            patch('pecha_api.auth.auth_service.generate_and_validate_username') as mock_generate_and_validate_username, \
            patch('pecha_api.auth.auth_service.link_or_create_author_for_user') as mock_link_or_create_author:
        mock_user = MagicMock()
        mock_save_user.return_value = mock_user
        mock_get_hashed_password.return_value = "hashed_password123"
        mock_generate_and_validate_username.return_value = 'john_doe.0003'

        response = create_user(create_user_request, registration_source)

        mock_get_hashed_password.assert_called_once_with("password123")
        mock_save_user.assert_called_once()
        mock_link_or_create_author.assert_called_once_with(db=ANY, user=mock_user)
        assert response == mock_user


def test_create_user_with_google_success():
    create_user_request = CreateUserRequest(
        firstname="John",
        lastname="Doe",
        email="test@gmail.com",
        password=""
    )
    registration_source = RegistrationSource.GOOGLE

    with patch('pecha_api.auth.auth_service.save_user') as mock_save_user, \
            patch('pecha_api.auth.auth_service.generate_and_validate_username') as mock_generate_and_validate_username, \
            patch('pecha_api.auth.auth_service.link_or_create_author_for_user') as mock_link_or_create_author:
        mock_user = MagicMock()
        mock_save_user.return_value = mock_user
        mock_generate_and_validate_username.return_value = 'john_doe.0003'

        response = create_user(create_user_request, registration_source)

        mock_save_user.assert_called_once()
        mock_link_or_create_author.assert_called_once_with(db=ANY, user=mock_user)
        assert response == mock_user


def test_create_user_with_facebook_success():
    create_user_request = CreateUserRequest(
        firstname="John",
        lastname="Doe",
        email="test@gmail.com",
        password=""
    )
    registration_source = RegistrationSource.FACEBOOK

    with patch('pecha_api.auth.auth_service.save_user') as mock_save_user, \
            patch('pecha_api.auth.auth_service.generate_and_validate_username') as mock_generate_and_validate_username, \
            patch('pecha_api.auth.auth_service.link_or_create_author_for_user') as mock_link_or_create_author:
        mock_user = MagicMock()
        mock_save_user.return_value = mock_user
        mock_generate_and_validate_username.return_value = 'john_doe.0003'

        response = create_user(create_user_request, registration_source)

        mock_save_user.assert_called_once()
        mock_link_or_create_author.assert_called_once_with(db=ANY, user=mock_user)
        assert response == mock_user


def test_create_user_links_existing_author_with_matching_email():
    """A new website User whose email matches an existing Author gets
    linked to that Author (Author.user_id) so both surfaces recognize the
    same person - handled by link_or_create_author_for_user, not by
    blocking the registration."""
    create_user_request = CreateUserRequest(
        firstname="John",
        lastname="Doe",
        email="author@example.com",
        password="password123"
    )
    registration_source = RegistrationSource.EMAIL

    with patch('pecha_api.auth.auth_service.save_user') as mock_save_user, \
            patch('pecha_api.auth.auth_service.get_hashed_password') as mock_get_hashed_password, \
            patch('pecha_api.auth.auth_service.generate_and_validate_username') as mock_generate_and_validate_username, \
            patch('pecha_api.auth.auth_service.link_or_create_author_for_user') as mock_link_or_create_author:
        mock_user = MagicMock()
        mock_save_user.return_value = mock_user
        mock_get_hashed_password.return_value = "hashed_password123"
        mock_generate_and_validate_username.return_value = 'john_doe.0003'

        response = create_user(create_user_request, registration_source)

        mock_save_user.assert_called_once()
        mock_link_or_create_author.assert_called_once_with(db=ANY, user=mock_user)
        assert response == mock_user


def test_create_user_with_empty_password():
    create_user_request = CreateUserRequest(
        firstname="John",
        lastname="Doe",
        email="test@example.com",
        password=""
    )
    registration_source = RegistrationSource.EMAIL
    with patch('pecha_api.auth.auth_service.generate_and_validate_username') as mock_generate_and_validate_username:
        try:
            mock_generate_and_validate_username.return_value = 'john_doe.0003'
            create_user(create_user_request, registration_source)
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == "Password cannot be empty"


def test_create_user_with_short_password():
    create_user_request = CreateUserRequest(
        firstname="John",
        lastname="Doe",
        email="test@example.com",
        password="short"
    )
    registration_source = RegistrationSource.EMAIL
    with patch('pecha_api.auth.auth_service.generate_and_validate_username') as mock_generate_and_validate_username:
        try:
            mock_generate_and_validate_username.return_value = 'john_doe.0003'
            create_user(create_user_request, registration_source)
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == "Password must be between 8 and 20 characters"


def test_validate_user_already_exist_user_exists():
    email = "existing@example.com"

    with patch('pecha_api.auth.auth_service.get_user_by_email') as mock_get_user_by_email:
        mock_get_user_by_email.return_value = MagicMock()

        try:
            validate_user_already_exist(email)
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == 'Email or username already exists'

        mock_get_user_by_email.assert_called_once_with(db=ANY, email=email)


def test_validate_user_already_exist_user_does_not_exist():
    email = "new@example.com"

    with patch('pecha_api.auth.auth_service.get_user_by_email') as mock_get_user_by_email:
        mock_get_user_by_email.return_value = None

        validate_user_already_exist(email)

        mock_get_user_by_email.assert_called_once_with(db=ANY, email=email)


def test_authenticate_and_generate_tokens_success():
    email = "test@example.com"
    password = "password123"
    user = MagicMock()
    user.email = email
    user.password = get_hashed_password(password)

    with patch('pecha_api.auth.auth_service.authenticate_user') as mock_authenticate_user, \
            patch('pecha_api.auth.auth_service.generate_token_user') as mock_generate_token_user:
        mock_authenticate_user.return_value = user
        mock_generate_token_user.return_value = {"access_token": "fake_access_token",
                                                 "refresh_token": "fake_refresh_token"}

        response = authenticate_and_generate_tokens(email, password)

        mock_authenticate_user.assert_called_once_with(email=email, password=password)
        mock_generate_token_user.assert_called_once_with(user)
        assert response == {"access_token": "fake_access_token", "refresh_token": "fake_refresh_token"}


def test_authenticate_and_generate_tokens_invalid_credentials():
    email = "invalid@example.com"
    password = "password123"

    with patch('pecha_api.auth.auth_service.authenticate_user') as mock_authenticate_user:
        mock_authenticate_user.side_effect = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                                           detail='Invalid email or password')
        try:
            authenticate_and_generate_tokens(email, password)
        except HTTPException as e:
            assert e.status_code == status.HTTP_401_UNAUTHORIZED
            assert e.detail == "Invalid email or password"
        mock_authenticate_user.assert_called_once_with(email=email, password=password)


def test_authenticate_and_generate_tokens_internal_server_error():
    email = "test@example.com"
    password = "password123"
    user = MagicMock()
    user.email = email
    user.password = get_hashed_password(password)

    with patch('pecha_api.auth.auth_service.authenticate_user') as mock_authenticate_user, \
            patch('pecha_api.auth.auth_service.generate_token_user') as mock_generate_token_user:
        mock_authenticate_user.return_value = user
        mock_generate_token_user.side_effect = HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                                                             detail='Internal Server Error')
        try:
            authenticate_and_generate_tokens(email, password)
        except HTTPException as e:
            assert e.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
            assert e.detail == "Internal Server Error"

        mock_authenticate_user.assert_called_once_with(email=email, password=password)
        mock_generate_token_user.assert_called_once_with(user)


def test_request_reset_password_success():
    email = "test@example.com"
    user = MagicMock()
    user.email = email
    user.registration_source = 'email'

    with patch('pecha_api.auth.auth_service.get_user_by_email') as mock_get_user_by_email, \
            patch('pecha_api.auth.auth_service.save_password_reset') as mock_save_password_reset, \
            patch('pecha_api.auth.auth_service.send_reset_email') as mock_send_reset_email:
        mock_get_user_by_email.return_value = user

        response = request_reset_password(email)

        mock_get_user_by_email.assert_called_once_with(db=ANY, email=email)
        mock_save_password_reset.assert_called_once()
        mock_send_reset_email.assert_called_once()
        assert response == {"message": "If the email exists in our system, a password reset email has been sent."}


def test_request_reset_password_not_from_email_412():
    email = "test@example.com"
    user = MagicMock()
    user.email = email
    user.registration_source = 'google-oauth2'

    with patch('pecha_api.auth.auth_service.get_user_by_email') as mock_get_user_by_email:
        mock_get_user_by_email.return_value = user
        try:
            request_reset_password(email)
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == "Registration Source Mismatch"


def test_request_reset_password_user_not_found():
    email = "nonexistent@example.com"
    with patch('pecha_api.auth.auth_service.get_user_by_email') as mock_get_user_by_email:
        mock_get_user_by_email.side_effect = HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                                           detail="User not found")
        try:
            request_reset_password(email)
        except HTTPException as e:
            assert e.status_code == status.HTTP_404_NOT_FOUND
            assert e.detail == 'User not found'
        mock_get_user_by_email.assert_called_once_with(db=ANY, email=email)


def test_update_password_success():
    token = "valid_token"
    password = "newpassword123"
    reset_entry = MagicMock()
    reset_entry.email = "test@example.com"
    reset_entry.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
    user = MagicMock()
    user.email = reset_entry.email
    user.password = "hashed_oldpassword123"
    user.registration_source = 'email'

    updated_user = MagicMock()
    updated_user.email = reset_entry.email
    updated_user.password = "hashed_newpassword123"

    with patch('pecha_api.auth.auth_service.get_password_reset_by_token') as mock_get_password_reset_by_token, \
            patch('pecha_api.auth.auth_service.get_user_by_email') as mock_get_user_by_email, \
            patch('pecha_api.auth.auth_service.get_hashed_password') as mock_get_hashed_password, \
            patch('pecha_api.auth.auth_service.save_user') as mock_save_user:
        mock_get_password_reset_by_token.return_value = reset_entry
        mock_get_user_by_email.return_value = user
        mock_get_hashed_password.return_value = "hashed_newpassword123"
        mock_save_user.return_value = updated_user

        response = update_password(token, password)

        mock_get_password_reset_by_token.assert_called_once_with(db=ANY, token=token)
        mock_get_user_by_email.assert_called_once_with(db=ANY, email=reset_entry.email)
        mock_get_hashed_password.assert_called_once_with(password)
        mock_save_user.assert_called_once_with(db=ANY, user=user)
        assert response.email == user.email
        assert response.password == user.password


def test_update_password_invalid_source_400():
    token = "valid_token"
    password = "newpassword123"
    reset_entry = MagicMock()
    reset_entry.email = "test@example.com"
    reset_entry.token_expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
    user = MagicMock()
    user.email = reset_entry.email
    user.password = "hashed_oldpassword123"
    user.registration_source = 'google-oauth2'

    updated_user = MagicMock()
    updated_user.email = reset_entry.email
    updated_user.password = "hashed_newpassword123"

    with patch('pecha_api.auth.auth_service.get_password_reset_by_token') as mock_get_password_reset_by_token, \
            patch('pecha_api.auth.auth_service.get_user_by_email') as mock_get_user_by_email:
        mock_get_password_reset_by_token.return_value = reset_entry
        mock_get_user_by_email.return_value = user

        try:
            update_password(token, password)
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == "Registration Source Mismatch"


def test_update_password_invalid_token():
    token = "invalid_token"
    password = "newpassword123"

    with patch('pecha_api.auth.auth_service.get_password_reset_by_token') as mock_get_password_reset_by_token:
        mock_get_password_reset_by_token.return_value = None

        try:
            update_password(token, password)
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == "Invalid or expired token"

        mock_get_password_reset_by_token.assert_called_once_with(db=ANY, token=token)


def test_update_password_expired_token():
    token = "expired_token"
    password = "newpassword123"
    reset_entry = MagicMock()
    reset_entry.token_expiry = datetime.now(timezone.utc) - timedelta(minutes=1)

    with patch('pecha_api.auth.auth_service.get_password_reset_by_token') as mock_get_password_reset_by_token:
        mock_get_password_reset_by_token.return_value = reset_entry

        try:
            update_password(token, password)
        except HTTPException as e:
            assert e.status_code == status.HTTP_400_BAD_REQUEST
            assert e.detail == "Invalid or expired token"

        mock_get_password_reset_by_token.assert_called_once_with(db=ANY, token=token)


def test_send_reset_email():
    email = "test@example.com"
    reset_link = "http://example.com/reset-password?token=valid_token"

    with patch('pecha_api.auth.auth_service.send_email') as mock_send_email, \
            patch('pecha_api.auth.auth_service.Template.render') as mock_render:
        mock_render.return_value = "rendered_html_content"

        send_reset_email(email, reset_link)

        mock_render.assert_called_once_with(reset_link=reset_link)
        mock_send_email.assert_called_once_with(
            to_email=email,
            subject="Pecha Password Reset",
            message="rendered_html_content"
        )


def test__validate_password_empty_password():
    password = ""

    try:
        _validate_password(password)
    except HTTPException as e:
        assert e.status_code == status.HTTP_400_BAD_REQUEST
        assert e.detail == "Password cannot be empty"


def test__validate_password_short_password():
    password = "short"

    try:
        _validate_password(password)
    except HTTPException as e:
        assert e.status_code == status.HTTP_400_BAD_REQUEST
        assert e.detail == "Password must be between 8 and 20 characters"


def test__validate_password_long_password():
    password = "a" * 21

    try:
        _validate_password(password)
    except HTTPException as e:
        assert e.status_code == status.HTTP_400_BAD_REQUEST
        assert e.detail == "Password must be between 8 and 20 characters"


def test__validate_password_valid_password():
    password = "validpassword"

    _validate_password(password)


def test_validate_username_user_exists():
    username = "existing_user"

    with patch('pecha_api.auth.auth_service.get_user_by_username') as mock_get_user_by_username:
        mock_get_user_by_username.return_value = MagicMock()

        result = validate_username(username)

        mock_get_user_by_username.assert_called_once_with(db=ANY, username=username)
        assert result is False


def test_validate_username_user_does_not_exist():
    username = "new_user"

    with patch('pecha_api.auth.auth_service.get_user_by_username') as mock_get_user_by_username:
        mock_get_user_by_username.return_value = None

        result = validate_username(username)

        mock_get_user_by_username.assert_called_once_with(db=ANY, username=username)
        assert result is True


def test_generate_username():
    first_name = "John"
    last_name = "Doe"

    username = generate_username(first_name, last_name)

    assert username.startswith("webuddhist_user_")
    parts = username.split(".")
    assert len(parts) == 2
    assert len(parts[1]) == 4  # random suffix


def test_generate_username_with_phone():
    first_name = "John"
    last_name = "Doe"
    phone_number = "+1-234-567-8900"

    username = generate_username(first_name, last_name, phone_number)

    assert username.startswith("webuddhist_john_doe_12345678900.")
    parts = username.split(".")
    assert len(parts) == 2
    assert len(parts[1]) == 4  # random suffix


def test_generate_and_validate_username_success():
    first_name = "John"
    last_name = "Doe"

    with patch('pecha_api.auth.auth_service.validate_username') as mock_validate_username:
        mock_validate_username.return_value = True

        username = generate_and_validate_username(first_name, last_name)

        mock_validate_username.assert_called()
        assert username.startswith("webuddhist_user_")


def test_generate_and_validate_username_with_phone_success():
    first_name = "John"
    last_name = "Doe"
    phone_number = "+1-234-567-8900"

    with patch('pecha_api.auth.auth_service.validate_username') as mock_validate_username:
        mock_validate_username.return_value = True

        username = generate_and_validate_username(first_name, last_name, phone_number)

        mock_validate_username.assert_called()
        assert username.startswith("webuddhist_john_doe_12345678900.")


def test_generate_and_validate_username_retry():
    first_name = "John"
    last_name = "Doe"

    with patch('pecha_api.auth.auth_service.validate_username') as mock_validate_username:
        mock_validate_username.side_effect = [False, True]

        username = generate_and_validate_username(first_name, last_name)

        assert mock_validate_username.call_count == 2
        assert username.startswith("webuddhist_user_")


def test_validate_username_returns_true_on_404():
    username = "maybe_new_user"

    with patch('pecha_api.auth.auth_service.get_user_by_username') as mock_get_user_by_username:
        mock_get_user_by_username.side_effect = HTTPException(status_code=status.HTTP_404_NOT_FOUND,
                                                              detail="Not Found")

        result = validate_username(username)

        mock_get_user_by_username.assert_called_once_with(db=ANY, username=username)
        assert result is True


def test_retrieve_client_info():
    with patch('pecha_api.auth.auth_service.get') as mock_get:
        mock_get.side_effect = ["test-client-id", "test-domain", "test-audience"]

        props = retrieve_client_info()

        assert props.client_id == "test-client-id"
        assert props.domain == "test-domain"
        assert props.audience == "test-audience"


def test_create_user_request_treats_blank_identifiers_as_absent():
    """`email` and `phone_number` are UNIQUE columns: '' would claim the one
    ''-slot in the table and make every later blank collide as a duplicate."""
    from pecha_api.auth.auth_models import CreateUserRequest

    request = CreateUserRequest(
        firstname="Webuddhist",
        lastname="_user_123456",
        email="someone@example.com",
        password="",
        phone_number="",
    )

    assert request.phone_number is None
    assert request.password is None
    assert request.email == "someone@example.com"


def test_create_user_request_keeps_real_identifiers():
    from pecha_api.auth.auth_models import CreateUserRequest

    request = CreateUserRequest(
        firstname="Webuddhist",
        lastname="_user_123456",
        email="",
        phone_number="+15551234567",
    )

    assert request.email is None
    assert request.phone_number == "+15551234567"
