import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

import jwt
from jose import JWTError
from jose.exceptions import ExpiredSignatureError as JoseExpiredSignatureError

from pecha_api.auth.auth0_sms import verify_auth0_sms_token
from ..config import get
from ..notification.email_provider import send_email
from .auth_models import CreateUserRequest, UserLoginResponse, RefreshTokenResponse, TokenResponse, UserInfo, \
    PropsResponse, PhoneExchangeRequest, PhoneExchangeResponse, PhoneLinkResponse
from ..users.users_models import Users, PasswordReset
from ..db.database import SessionLocal
from ..users.users_repository import (
    get_user_by_email,
    get_user_by_phone,
    get_user_by_username,
    link_user_phone,
    save_phone_user,
    save_user,
)
from ..plans.authors.author_user_link_service import link_or_create_author_for_user
from ..users.user_resolution import resolve_user_from_payload
from .auth_repository import (
    create_access_token,
    create_refresh_token,
    decode_backend_token,
    generate_token_data,
    get_hashed_password,
    validate_token,
    verify_password,
)
from .password_reset_repository import save_password_reset, get_password_reset_by_token
from .auth_enums import RegistrationSource
from fastapi import HTTPException
from starlette import status
from jinja2 import Template
from pathlib import Path


def register_user_with_source(create_user_request: CreateUserRequest, registration_source: RegistrationSource):
    registered_user = create_user(
        create_user_request=create_user_request,
        registration_source=registration_source
    )
    return generate_token_user(registered_user)


def _require_email_or_phone(create_user_request: CreateUserRequest) -> None:
    if not create_user_request.email and not create_user_request.phone_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either email or phone number is required"
        )


def _apply_phone_registration(create_user_request: CreateUserRequest) -> None:
    if not create_user_request.phone_number:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phone number is required for phone registration"
        )
    with SessionLocal() as db_session:
        if get_user_by_phone(db_session, create_user_request.phone_number):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Phone number already registered"
            )


def _apply_email_registration(create_user_request: CreateUserRequest, new_user: Users) -> None:
    if not create_user_request.email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email is required for email registration"
        )
    _validate_password(create_user_request.password)
    new_user.password = get_hashed_password(create_user_request.password)


def create_user(create_user_request: CreateUserRequest, registration_source: RegistrationSource) -> Users:
    logging.debug(f"RegistrationSource: {registration_source.value}")
    logging.debug(f"Creating user with first name: {create_user_request.firstname}")

    _require_email_or_phone(create_user_request)

    new_user = Users(**create_user_request.model_dump(exclude_unset=True))
    new_user.is_admin = False
    new_user.username = generate_and_validate_username(
        first_name=create_user_request.firstname,
        last_name=create_user_request.lastname,
        phone_number=create_user_request.phone_number,
    )

    if registration_source == RegistrationSource.PHONE:
        _apply_phone_registration(create_user_request)
    if registration_source == RegistrationSource.EMAIL:
        _apply_email_registration(create_user_request, new_user)

    # For social logins (Google, Facebook, Apple, etc.), password is not required
    new_user.registration_source = registration_source.value

    with SessionLocal() as db_session:
        saved_user = save_user(db=db_session, user=new_user)
        link_or_create_author_for_user(db=db_session, user=saved_user)
        return saved_user


def _validate_password(password: str):
    if not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Password cannot be empty")
    if len(password) < 8 or len(password) > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Password must be between 8 and 20 characters")


def validate_user_already_exist(email: str):
    with SessionLocal() as db_session:
        existing_user_by_email = get_user_by_email(db=db_session, email=email)
        if existing_user_by_email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Email or username already exists')


def authenticate_and_generate_tokens(email: str, password: str):
    user = authenticate_user(email=email, password=password)
    return generate_token_user(user)


def generate_token_user(user: Users):
    data = generate_token_data(user)
    access_token = create_access_token(data)
    refresh_token = create_refresh_token(data)

    token_response = TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer"
    )
    return UserLoginResponse(
        user=UserInfo(
            name=user.firstname + " " + user.lastname,
            avatar_url=user.avatar_url
        ),
        auth=token_response
    )


def authenticate_user(email: str, password: str):
    with SessionLocal() as db_session:
        user = get_user_by_email(db=db_session, email=email)
        if not verify_password(
                plain_password=password,
                hashed_password=user.password
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail='Invalid email or password')
        return user


def refresh_access_token(refresh_token: str):
    try:
        payload = validate_token(refresh_token)
        with SessionLocal() as db_session:
            try:
                user = resolve_user_from_backend_payload(db_session, payload)
            except HTTPException as exception:
                if exception.status_code == status.HTTP_401_UNAUTHORIZED:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Invalid refresh token",
                    ) from exception
                raise
            data = generate_token_data(user)
            access_token = create_access_token(data=data)
            return RefreshTokenResponse(
                access_token=access_token,
                token_type="Bearer"
            )
    except (jwt.ExpiredSignatureError, JoseExpiredSignatureError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")
    except (jwt.PyJWTError, JWTError, KeyError, TypeError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")


def resolve_user_from_backend_payload(db, payload: Dict[str, Any]) -> Users:
    return resolve_user_from_payload(
        db=db,
        payload=payload,
        unauthorized_detail="Invalid backend token",
    )


def _phone_exchange_response(user: Users, phone_number: str) -> PhoneExchangeResponse:
    login_response = generate_token_user(user)
    return PhoneExchangeResponse(
        user_id=user.id,
        phone_number=phone_number,
        message="Authentication successful",
        user=login_response.user,
        auth=login_response.auth,
    )


def exchange_phone_token(request: PhoneExchangeRequest) -> PhoneExchangeResponse:
    sms_identity = verify_auth0_sms_token(request.auth0_token)
    with SessionLocal() as db:
        user = get_user_by_phone(db=db, phone_number=sms_identity.phone_number)
        if user is not None:
            return _phone_exchange_response(user, sms_identity.phone_number)

        first_name = (request.first_name or "").strip()
        last_name = (request.last_name or "").strip()
        if not first_name or not last_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="First name and last name are required for a new phone profile",
            )

        user = Users(
            firstname=first_name,
            lastname=last_name,
            username=generate_and_validate_username(
                first_name=first_name,
                last_name=last_name,
            ),
            email=None,
            phone_number=sms_identity.phone_number,
            password=None,
            registration_source=RegistrationSource.PHONE.value,
            is_active=True,
            is_admin=False,
        )
        user = save_phone_user(db=db, user=user)
        link_or_create_author_for_user(db=db, user=user)
        return _phone_exchange_response(user, sms_identity.phone_number)


def _validate_backend_token(token: str) -> Dict[str, Any]:
    return decode_backend_token(token)


def link_phone_identity(backend_token: str, auth0_token: str) -> PhoneLinkResponse:
    try:
        backend_payload = _validate_backend_token(backend_token)
    except (JWTError, KeyError, TypeError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid backend token",
        )
    sms_identity = verify_auth0_sms_token(auth0_token)

    with SessionLocal() as db:
        user = resolve_user_from_backend_payload(db, backend_payload)
        phone_user = get_user_by_phone(
            db=db,
            phone_number=sms_identity.phone_number,
        )
        if phone_user is not None and phone_user.id != user.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Phone number is already linked to another user",
            )
        if user.phone_number != sms_identity.phone_number:
            link_user_phone(
                db=db,
                user=user,
                phone_number=sms_identity.phone_number,
            )

        return PhoneLinkResponse(
            user_id=user.id,
            phone_number=sms_identity.phone_number,
            message="Phone identity linked",
        )


def request_reset_password(email: str):
    with SessionLocal() as db_session:
        current_user = get_user_by_email(
            db=db_session,
            email=email
        )
        if current_user.registration_source != 'email':
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Registration Source Mismatch")

        reset_token = secrets.token_urlsafe(32)
        token_expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
        password_reset = PasswordReset(
            email=current_user.email,
            reset_token=reset_token,
            token_expiry=token_expiry
        )
        save_password_reset(
            db=db_session,
            password_reset=password_reset
        )
        reset_link = f"{get('BASE_URL')}/reset-password?token={reset_token}"
        send_reset_email(email=email, reset_link=reset_link)
        return {"message": "If the email exists in our system, a password reset email has been sent."}


def update_password(token: str, password: str):
    with SessionLocal() as db_session:
        reset_entry = get_password_reset_by_token(
            db=db_session,
            token=token
        )
        if reset_entry is None or reset_entry.token_expiry < datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
        current_user = get_user_by_email(
            db=db_session,
            email=reset_entry.email
        )
        if current_user.registration_source != 'email':
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Registration Source Mismatch")

        _validate_password(password)
        hashed_password = get_hashed_password(password)
        current_user.password = hashed_password
        updated_user = save_user(db=db_session, user=current_user)
        return updated_user


def send_reset_email(email: str, reset_link: str):
    template_path = Path(__file__).parent / "templates" / "reset_password_template.html"
    with open(template_path, "r") as f:
        template = Template(f.read())
    html_content = template.render(reset_link=reset_link)

    send_email(
        to_email=email,
        subject="Pecha Password Reset",
        message=html_content
    )


def validate_username(username: str) -> bool:
    with SessionLocal() as db_session:
        try:
            user = get_user_by_username(db=db_session, username=username)
        except HTTPException as e:
            if e.status_code == status.HTTP_404_NOT_FOUND:
                return True
            print(f"Error: {e}")
        return user is None


def generate_username(first_name: str, last_name: str, phone_number: str = None) -> str:
    """
    Generate a username based on the following logic:
    - If phone_number is present: webuddhist_{firstname}_{lastname}_{phonenumber}
    - If phone_number is NOT present: webuddhist_user_{random_6_digit}

    Uses cryptographically secure random number generation for username uniqueness.
    """
    random_suffix = str(secrets.randbelow(9999) + 1).zfill(4)

    if phone_number:
        # Sanitize phone number - remove all non-digit characters
        sanitized_phone = ''.join(filter(str.isdigit, phone_number))
        return f"webuddhist_{first_name.lower()}_{last_name.lower()}_{sanitized_phone}.{random_suffix}"
    else:
        # Use random fallback if no phone number
        random_num = str(secrets.randbelow(900000) + 100000)
        return f"webuddhist_user_{random_num}.{random_suffix}"


def generate_and_validate_username(first_name: str, last_name: str, phone_number: str = None) -> str:
    """
    Generate and validate a unique username.
    Keeps generating new usernames until a unique one is found.
    """
    while True:  # Loop until a valid username is generated
        username = generate_username(first_name=first_name, last_name=last_name, phone_number=phone_number)
        if validate_username(username=username):
            return username


def retrieve_client_info():
    props_response = PropsResponse(
        client_id=get("CLIENT_ID"),
        domain=get("DOMAIN_NAME"),
        audience=get("AUTH0_AUDIENCE"),
    )
    return props_response
