import secrets
from uuid import UUID

from .plan_auth_enums import AuthorStatus
from .plan_auth_models import CreateAuthorRequest, AuthorDetails, TokenPayload, \
    AuthorVerificationResponse, ResponseError, TokenResponse, AuthorLoginResponse, AuthorInfo, EmailReVerificationResponse, RefreshTokenResponse, \
    PhoneExchangeRequest, PhoneExchangeResponse, PhoneLinkResponse, \
    GoogleExchangeRequest, GoogleExchangeResponse, \
    EmailExchangeRequest, EmailExchangeResponse
from pecha_api.auth.auth0_sms import AUTH0_SMS_PROVIDER, verify_auth0_sms_token
from pecha_api.auth.auth0_google import AUTH0_GOOGLE_PROVIDER, verify_auth0_google_token
from pecha_api.auth.auth0_email import AUTH0_EMAIL_PROVIDER, verify_auth0_email_token
from pecha_api.plans.authors.plan_authors_model import Author, AuthorPasswordReset
from pecha_api.plans.authors.author_user_link_service import link_or_create_user_for_author
from pecha_api.db.database import SessionLocal
from pecha_api.plans.authors.plan_authors_repository import (
    check_author_exists,
    find_author_by_email,
    get_author_by_email,
    get_author_by_id,
    get_author_by_phone,
    link_author_phone,
    save_author,
    save_google_author,
    save_phone_author,
    update_author,
)
from pecha_api.auth.auth_repository import get_hashed_password, verify_password, create_access_token, create_refresh_token
from pecha_api.auth.password_reset_repository import save_password_reset, get_password_reset_by_token_for_author
from pecha_api.auth.auth_service import send_reset_email
from pecha_api.plans.groups.groups_service import notify_pending_group_invites
from fastapi import HTTPException
from starlette import status
from datetime import datetime, timedelta, timezone
from jose import jwt
from pecha_api.config import get
from pecha_api.notification.email_provider import send_email
from jinja2 import Template
from pathlib import Path
from typing import Dict, Any
from pecha_api.plans.response_message import (
    PASSWORD_EMPTY,
    PASSWORD_LENGTH_INVALID,
    TOKEN_EXPIRED,
    TOKEN_INVALID,
    EMAIL_VERIFIED_SUCCESS, 
    EMAIL_ALREADY_VERIFIED,
    REGISTRATION_MESSAGE,
    AUTHOR_NOT_VERIFIED,
    AUTHOR_NOT_ACTIVE,
    INVALID_EMAIL_PASSWORD,
    AUTHOR_NOT_FOUND,
    BAD_REQUEST,
    EMAIL_IS_SENT
)

def _get_author_full_name(author: Author) -> str:
    """Helper function to get author's full name"""
    return f"{author.first_name} {author.last_name}"


def _execute_with_session(operation):
    """Helper function to execute database operations with session management"""
    with SessionLocal() as db_session:
        return operation(db_session)


def register_author(create_user_request: CreateAuthorRequest) -> AuthorDetails:
    # Check for existing author to return required error shape on duplicates
    _execute_with_session(lambda db: check_author_exists(db=db, email=create_user_request.email))
    registered_user = _create_user(
        create_user_request=create_user_request
    )
    return registered_user

def _create_user(create_user_request: CreateAuthorRequest) -> AuthorDetails:
    new_author = Author(**create_user_request.model_dump())
    new_author.created_by = create_user_request.email
    _validate_password(new_author.password)
    hashed_password = get_hashed_password(new_author.password)
    new_author.password = hashed_password
    def _save_and_link(db):
        author = save_author(db=db, author=new_author)
        link_or_create_user_for_author(db=db, author=author)
        return author

    saved_author = _execute_with_session(_save_and_link)
    _send_verification_email(email=saved_author.email)
    return AuthorDetails(
        first_name=saved_author.first_name,
        last_name=saved_author.last_name,
        email=saved_author.email,
        status=AuthorStatus.PENDING_VERIFICATION,
        message=REGISTRATION_MESSAGE
    )

def _validate_password(password: str):
    if not password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=PASSWORD_EMPTY)
    if len(password) < 6:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=PASSWORD_LENGTH_INVALID)


def _generate_author_verification_token(email: str) -> str:
    expires_delta = timedelta(hours=24)
    expire = datetime.now(timezone.utc) + expires_delta

    payload = TokenPayload(
        email=email,
        iss=get("JWT_ISSUER"),
        aud=get("JWT_AUD"),
        iat=datetime.now(timezone.utc),
        exp=expire,
        typ="author_email_verification"
    )
    return jwt.encode(payload.model_dump(), get("JWT_SECRET_KEY"), algorithm=get("JWT_ALGORITHM"))

def _send_verification_email(email: str) -> None:
    token = _generate_author_verification_token(email=email)
    frontend_endpoint = get("WEBUDDHIST_STUDIO_BASE_URL")       
    verify_link = f"{frontend_endpoint}/verify-email?token={token}"

    template_path = Path(__file__).parent / "templates" / "verify_email_template.html"
    with open(template_path, "r") as f:
        template = Template(f.read())
    html_content = template.render(verify_link=verify_link)
    send_email(
        to_email=email,
        subject="Verify your Pecha account",
        message=html_content
    )




def verify_author_email(token: str) -> AuthorVerificationResponse:
    try:
        payload = jwt.decode(
            token,
            get("JWT_SECRET_KEY"),
            algorithms=[get("JWT_ALGORITHM")],
            audience=get("JWT_AUD")
        )
        if payload.get("typ") != "author_email_verification":
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TOKEN_INVALID)
        email = payload.get("email")
        if not email:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TOKEN_INVALID)
        with SessionLocal() as db_session:
            author = get_author_by_email(db=db_session, email=email) # need validation for author
            if not author.is_verified:
                author.is_verified = True
                update_author(db=db_session, author=author)
                notify_pending_group_invites(author)
                message = EMAIL_VERIFIED_SUCCESS
            else:
                message = EMAIL_ALREADY_VERIFIED
            return AuthorVerificationResponse(
                email=author.email,
                status=AuthorStatus.INACTIVE,
                message=message
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TOKEN_EXPIRED)
    except HTTPException as e:
        # Re-raise expected HTTP errors (type/payload validation) without masking
        raise e
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TOKEN_INVALID)


def authenticate_author(email: str, password: str):
    with SessionLocal() as db_session:
        author = get_author_by_email(db=db_session, email=email)
        if not verify_password(
                plain_password=password,
                hashed_password=author.password
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=INVALID_EMAIL_PASSWORD
            )
        check_verified_author(author=author)
        return author

def check_verified_author(author: Author) -> bool:
    if not author.is_verified:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail = AUTHOR_NOT_VERIFIED)
    elif not author.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail = AUTHOR_NOT_ACTIVE)    
    

def authenticate_and_generate_tokens(email: str, password: str):
    author = authenticate_author(email=email, password=password)
    return generate_token_author(author)

def generate_author_token_data(author: Author):
    if not all([author.id, author.first_name, author.last_name]):
        return None
    data = {
        "sub": str(author.id),
        "name": _get_author_full_name(author),
        "iss": get("JWT_ISSUER"),
        "aud": get("JWT_AUD"),
        "iat": datetime.now(timezone.utc)
    }
    if author.email:
        data["email"] = author.email
    if author.phone_number:
        data["phone_number"] = author.phone_number
    return data

def generate_token_author(author: Author):
    data = generate_author_token_data(author)
    access_token = create_access_token(data)
    refresh_token = create_refresh_token(data)

    token_response = TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="Bearer"
    )
    return AuthorLoginResponse(
        user=AuthorInfo(
            name=_get_author_full_name(author),
            image_url=author.image_url
        ),
        auth=token_response
    )


def request_reset_password(email: str):
    with SessionLocal() as db_session:
        current_user = get_author_by_email(
            db=db_session,
            email=email
        )
        reset_token = secrets.token_urlsafe(32)
        token_expiry = datetime.now(timezone.utc) + timedelta(minutes=30)
        password_reset = AuthorPasswordReset(
            email=current_user.email,
            reset_token=reset_token,
            token_expiry=token_expiry
        )
        save_password_reset(
            db=db_session,
            password_reset=password_reset
        )
        reset_link = f"{get('WEBUDDHIST_STUDIO_BASE_URL')}/reset-password?token={reset_token}&email={email}"
        send_reset_email(email=email, reset_link=reset_link)
        return {"message": "If the email exists in our system, a password reset email has been sent."}


def update_password(token: str, password: str):
    with SessionLocal() as db_session:
        reset_entry = get_password_reset_by_token_for_author(
            db=db_session,
            token=token
        )
        if reset_entry is None or reset_entry.token_expiry < datetime.now(timezone.utc):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
        current_user = get_author_by_email(
            db=db_session,
            email=reset_entry.email
        )
        _validate_password(password)
        hashed_password = get_hashed_password(password)
        current_user.password = hashed_password
        updated_user = save_author(db=db_session, author=current_user)
        return updated_user

def re_verify_email(email: str) -> EmailReVerificationResponse:
    with SessionLocal() as db_session:
        author = get_author_by_email(db=db_session, email=email)
        if not author:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ResponseError(error=BAD_REQUEST, message=AUTHOR_NOT_FOUND).model_dump())
        _send_verification_email(email=email)
    return EmailReVerificationResponse(message=EMAIL_IS_SENT)


def refresh_access_token(refresh_token: str):
    try:
        payload = _validate_token(refresh_token)
        with SessionLocal() as db_session:
            try:
                author = resolve_author_from_backend_payload(db_session, payload)
            except HTTPException:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid refresh token",
                )
            data = generate_author_token_data(author)
            access_token = create_access_token(data=data)
            return RefreshTokenResponse(
                access_token=access_token,
                token_type="Bearer"
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token expired")
    except jwt.JWTError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

def _validate_token(token: str):
    return jwt.decode(
        token,
        get("JWT_SECRET_KEY"),
        algorithms=[get("JWT_ALGORITHM")],
        audience=get("JWT_AUD")
    )


def resolve_author_from_backend_payload(db, payload: Dict[str, Any]) -> Author:
    subject = payload.get("sub")
    if subject is not None:
        try:
            return get_author_by_id(db=db, author_id=UUID(str(subject)))
        except (TypeError, ValueError):
            pass

    email = payload.get("email")
    if isinstance(email, str) and email:
        return get_author_by_email(db=db, email=email)
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid backend token",
    )


def _phone_exchange_response(author: Author, phone_number: str) -> PhoneExchangeResponse:
    author_status = AuthorStatus.ACTIVE if author.is_active else AuthorStatus.INACTIVE
    token_response = None
    message = AUTHOR_NOT_ACTIVE
    if author.is_verified and author.is_active:
        token_response = generate_token_author(author).auth
        message = "Authentication successful"
    return PhoneExchangeResponse(
        author_id=author.id,
        phone_number=phone_number,
        status=author_status,
        message=message,
        user=AuthorInfo(
            name=_get_author_full_name(author),
            image_url=author.image_url,
        ),
        auth=token_response,
    )


def exchange_phone_token(request: PhoneExchangeRequest) -> PhoneExchangeResponse:
    sms_identity = verify_auth0_sms_token(request.auth0_token)
    with SessionLocal() as db:
        author = get_author_by_phone(db=db, phone_number=sms_identity.phone_number)
        if author is not None:
            return _phone_exchange_response(author, sms_identity.phone_number)

        first_name = (request.first_name or "").strip()
        last_name = (request.last_name or "").strip()
        if not first_name or not last_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="First name and last name are required for a new phone profile",
            )

        author = Author(
            first_name=first_name,
            last_name=last_name,
            email=None,
            phone_number=sms_identity.phone_number,
            password=None,
            is_verified=True,
            is_active=False,
            created_by=f"{AUTH0_SMS_PROVIDER}:{sms_identity.subject}",
        )
        author = save_phone_author(db=db, author=author)
        link_or_create_user_for_author(db=db, author=author)
        notify_pending_group_invites(author)
        return _phone_exchange_response(author, sms_identity.phone_number)


def link_phone_identity(backend_token: str, auth0_token: str) -> PhoneLinkResponse:
    try:
        backend_payload = _validate_token(backend_token)
    except jwt.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid backend token",
        )
    sms_identity = verify_auth0_sms_token(auth0_token)

    with SessionLocal() as db:
        author = resolve_author_from_backend_payload(db, backend_payload)
        check_verified_author(author)
        phone_author = get_author_by_phone(
            db=db,
            phone_number=sms_identity.phone_number,
        )
        if phone_author is not None and phone_author.id != author.id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Phone number is already linked to another author",
            )
        if author.phone_number != sms_identity.phone_number:
            link_author_phone(
                db=db,
                author=author,
                phone_number=sms_identity.phone_number,
            )

        return PhoneLinkResponse(
            author_id=author.id,
            phone_number=sms_identity.phone_number,
            message="Phone identity linked",
        )


def _google_exchange_response(author: Author, email: str) -> GoogleExchangeResponse:
    author_status = AuthorStatus.ACTIVE if author.is_active else AuthorStatus.INACTIVE
    token_response = None
    message = AUTHOR_NOT_ACTIVE
    if author.is_verified and author.is_active:
        token_response = generate_token_author(author).auth
        message = "Authentication successful"
    return GoogleExchangeResponse(
        author_id=author.id,
        email=email,
        status=author_status,
        message=message,
        user=AuthorInfo(
            name=_get_author_full_name(author),
            image_url=author.image_url,
        ),
        auth=token_response,
    )


def exchange_google_token(request: GoogleExchangeRequest) -> GoogleExchangeResponse:
    google_identity = verify_auth0_google_token(request.auth0_token)
    with SessionLocal() as db:
        author = find_author_by_email(db=db, email=google_identity.email)
        if author is not None:
            if not author.is_verified:
                author.is_verified = True
                author = update_author(db=db, author=author)
                notify_pending_group_invites(author)
            return _google_exchange_response(author, google_identity.email)

        first_name = (request.first_name or google_identity.first_name or "").strip()
        last_name = (request.last_name or google_identity.last_name or "").strip()
        if not first_name or not last_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="First name and last name are required for a new phone profile",
            )

        author = Author(
            first_name=first_name,
            last_name=last_name,
            email=google_identity.email,
            phone_number=None,
            password=None,
            is_verified=True,
            is_active=False,
            created_by=f"{AUTH0_GOOGLE_PROVIDER}:{google_identity.subject}",
        )
        author = save_google_author(db=db, author=author)
        link_or_create_user_for_author(db=db, author=author)
        notify_pending_group_invites(author)
        return _google_exchange_response(author, google_identity.email)


def _email_exchange_response(author: Author, email: str) -> EmailExchangeResponse:
    author_status = AuthorStatus.ACTIVE if author.is_active else AuthorStatus.INACTIVE
    token_response = None
    message = AUTHOR_NOT_ACTIVE
    if author.is_verified and author.is_active:
        token_response = generate_token_author(author).auth
        message = "Authentication successful"
    return EmailExchangeResponse(
        author_id=author.id,
        email=email,
        status=author_status,
        message=message,
        user=AuthorInfo(
            name=_get_author_full_name(author),
            image_url=author.image_url,
        ),
        auth=token_response,
    )


def exchange_email_token(request: EmailExchangeRequest) -> EmailExchangeResponse:
    email_identity = verify_auth0_email_token(request.auth0_token)
    with SessionLocal() as db:
        author = find_author_by_email(db=db, email=email_identity.email)
        if author is not None:
            if not author.is_verified:
                # Auth0 already verified this email before issuing the token.
                author.is_verified = True
                author = update_author(db=db, author=author)
                notify_pending_group_invites(author)
            return _email_exchange_response(author, email_identity.email)

        first_name = (request.first_name or email_identity.first_name or "").strip()
        last_name = (request.last_name or email_identity.last_name or "").strip()
        if not first_name or not last_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="First name and last name are required for a new phone profile",
            )

        author = Author(
            first_name=first_name,
            last_name=last_name,
            email=email_identity.email,
            phone_number=None,
            password=None,
            is_verified=True,
            is_active=False,
            created_by=f"{AUTH0_EMAIL_PROVIDER}:{email_identity.subject}",
        )
        author = save_google_author(db=db, author=author)
        link_or_create_user_for_author(db=db, author=author)
        notify_pending_group_invites(author)
        return _email_exchange_response(author, email_identity.email)

