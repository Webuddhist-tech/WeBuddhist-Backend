import secrets
from typing import Dict, Any, Optional, Tuple
from uuid import UUID

from .plan_auth_enums import AuthorStatus
from .plan_auth_models import CreateAuthorRequest, AuthorDetails, TokenPayload, \
    AuthorVerificationResponse, ResponseError, TokenResponse, AuthorLoginResponse, AuthorInfo, EmailReVerificationResponse, RefreshTokenResponse, \
    PhoneExchangeRequest, PhoneExchangeResponse, PhoneLinkResponse, \
    GoogleExchangeRequest, GoogleExchangeResponse, \
    EmailExchangeRequest, EmailExchangeResponse, \
    InviteRegisterRequest, AppLoginRequest, AppLoginResponse
from .studio_access_service import StudioAdmission, account_status, admit_author, not_active_message
from pecha_api.auth.auth0_sms import AUTH0_SMS_PROVIDER, verify_auth0_sms_token
from pecha_api.auth.auth0_google import AUTH0_GOOGLE_PROVIDER, verify_auth0_google_token
from pecha_api.auth.auth0_email import AUTH0_EMAIL_PROVIDER, verify_auth0_email_token
from pecha_api.plans.authors.plan_authors_model import Author, AuthorPasswordReset
from pecha_api.plans.authors.author_user_link_service import (
    link_or_create_author_for_user,
    link_or_create_user_for_author,
)
from pecha_api.db.database import SessionLocal
from pecha_api.plans.authors.plan_authors_repository import (
    check_author_exists,
    find_author_by_email,
    find_author_by_user_id,
    get_author_by_email,
    get_author_by_id,
    get_author_by_phone,
    link_author_phone,
    save_author,
    save_google_author,
    save_phone_author,
    update_author,
)
from pecha_api.auth.auth_repository import get_hashed_password, verify_password, create_access_token, create_refresh_token, is_refresh_token_payload
from pecha_api.auth.password_reset_repository import save_password_reset, get_password_reset_by_token_for_author
from pecha_api.auth.auth_service import send_reset_email
from pecha_api.plans.groups.group_invite_token import decode_invite_token
from pecha_api.plans.groups.groups_repository import get_invite_by_id
from pecha_api.plans.groups.groups_service import _assert_invite_pending_for_recipient, notify_pending_group_invites
from pecha_api.users.users_repository import get_user_by_email_or_none
from fastapi import HTTPException
from starlette import status
from datetime import datetime, timedelta, timezone
from jose import jwt
from pecha_api.config import get, get_float
from pecha_api.notification.email_provider import send_email
from jinja2 import Template
from pathlib import Path
from pecha_api.plans.response_message import (
    PASSWORD_EMPTY,
    PASSWORD_LENGTH_INVALID,
    TOKEN_EXPIRED,
    TOKEN_INVALID,
    EMAIL_VERIFIED_ACTIVE,
    EMAIL_ALREADY_VERIFIED,
    REGISTRATION_MESSAGE,
    AUTHOR_NOT_VERIFIED,
    AUTHOR_NOT_ACTIVE,
    INVALID_EMAIL_PASSWORD,
    AUTHOR_NOT_FOUND,
    BAD_REQUEST,
    EMAIL_IS_SENT
)

PROFILE_NAMES_REQUIRED = "First name and last name are required for a new phone profile"
INVITE_EMAIL_MISMATCH = "This invitation was sent to a different email address"
INVITE_ACCOUNT_EXISTS = "An account already uses this email. Sign in to accept the invitation."
APP_ACCOUNT_CONFLICT = (
    "A Studio account already uses this email or phone number. Sign in with that account instead."
)
AUTHENTICATION_SUCCESSFUL = "Authentication successful"

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


def _sign_in_status(author: Author) -> AuthorStatus:
    # `status` stays ACTIVE/INACTIVE - the Studio branches on INACTIVE.
    return AuthorStatus.ACTIVE if author.is_active else AuthorStatus.INACTIVE


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
            admission = StudioAdmission()
            if not author.is_verified:
                author.is_verified = True
                update_author(db=db_session, author=author)
                admission = admit_author(db_session, author)
                notify_pending_group_invites(author)
                message = EMAIL_VERIFIED_ACTIVE if author.is_active else not_active_message(author)
            else:
                message = EMAIL_ALREADY_VERIFIED
            return AuthorVerificationResponse(
                email=author.email,
                status=_sign_in_status(author),
                account_status=account_status(author),
                message=message,
                joined_group_ids=admission.joined_group_ids,
            )
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TOKEN_EXPIRED)
    except HTTPException as e:
        # Re-raise expected HTTP errors (type/payload validation) without masking
        raise e
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=TOKEN_INVALID)


def _prove_email_with_invite(db, author: Author, invite_token: str) -> None:
    """An invite link reached this inbox, so it proves the author owns the
    address - an unverified account becomes verified."""
    _, target_email = decode_invite_token(invite_token)
    if (author.email or "").lower() != target_email:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=INVITE_EMAIL_MISMATCH)
    if not author.is_verified:
        author.is_verified = True
        update_author(db=db, author=author)


def authenticate_author(
    email: str,
    password: str,
    *,
    invite_token: Optional[str] = None,
    join_link_token: Optional[str] = None,
) -> Tuple[Author, StudioAdmission]:
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
        if invite_token:
            _prove_email_with_invite(db_session, author, invite_token)
        if not author.is_verified:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=AUTHOR_NOT_VERIFIED)
        admission = admit_author(db_session, author, join_link_token=join_link_token)
        check_verified_author(author=author)
        return author, admission

def check_verified_author(author: Author) -> bool:
    if not author.is_verified:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail = AUTHOR_NOT_VERIFIED)
    elif not author.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail = AUTHOR_NOT_ACTIVE)


def authenticate_and_generate_tokens(
    email: str,
    password: str,
    *,
    invite_token: Optional[str] = None,
    join_link_token: Optional[str] = None,
):
    author, admission = authenticate_author(
        email=email,
        password=password,
        invite_token=invite_token,
        join_link_token=join_link_token,
    )
    return _login_response(author, admission)


def _login_response(author: Author, admission: StudioAdmission) -> AuthorLoginResponse:
    response = generate_token_author(author)
    response.joined_group_ids = admission.joined_group_ids
    response.join_link_error = admission.join_link_error
    return response


def register_author_from_invite(request: InviteRegisterRequest) -> AuthorLoginResponse:
    """One step from an invite email to signed in and inside the group: the
    link proves the email, so there's no verify-email trip, and the invite is
    accepted on the way in."""
    invite_id, target_email = decode_invite_token(request.invite_token)
    first_name = (request.first_name or "").strip()
    last_name = (request.last_name or "").strip()
    if not first_name or not last_name:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=PROFILE_NAMES_REQUIRED)
    _validate_password(request.password)

    with SessionLocal() as db:
        if find_author_by_email(db=db, email=target_email) is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=INVITE_ACCOUNT_EXISTS)
        invite = get_invite_by_id(db=db, invite_id=invite_id)
        if invite is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invite not found")
        _assert_invite_pending_for_recipient(invite=invite, author_email=target_email)

        author = save_author(
            db=db,
            author=Author(
                first_name=first_name,
                last_name=last_name,
                email=target_email,
                password=get_hashed_password(request.password),
                is_verified=True,
                is_active=False,
                created_by=target_email,
            ),
        )
        link_or_create_user_for_author(db=db, author=author)
        admission = admit_author(db, author)
        check_verified_author(author=author)
        return _login_response(author, admission)

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

def _cms_access_token_expiry() -> timedelta:
    """Studio-only lifetime. The app's tokens keep the shared defaults in
    auth_repository; Studio overrides them so an author stays signed in for
    two days and can renew silently for a month."""
    return timedelta(days=get_float("CMS_ACCESS_TOKEN_EXPIRE_DAYS"))


def _cms_refresh_token_expiry() -> timedelta:
    return timedelta(days=get_float("CMS_REFRESH_TOKEN_EXPIRE_DAYS"))


def generate_token_author(author: Author):
    data = generate_author_token_data(author)
    access_token = create_access_token(data, expires_delta=_cms_access_token_expiry())
    refresh_token = create_refresh_token(data, expires_delta=_cms_refresh_token_expiry())

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
            access_token = create_access_token(data=data, expires_delta=_cms_access_token_expiry())
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


def _exchange_fields(author: Author, admission: StudioAdmission, *, can_sign_in: bool) -> Dict[str, Any]:
    """The status/tokens part every Studio sign-in exchange returns."""
    token_response = None
    message = not_active_message(author)
    if can_sign_in and author.is_active:
        token_response = generate_token_author(author).auth
        message = AUTHENTICATION_SUCCESSFUL
    return dict(
        status=_sign_in_status(author),
        account_status=account_status(author),
        message=message,
        user=AuthorInfo(
            name=_get_author_full_name(author),
            image_url=author.image_url,
        ),
        auth=token_response,
        joined_group_ids=admission.joined_group_ids,
        join_link_error=admission.join_link_error,
    )


def _phone_exchange_response(
    author: Author,
    phone_number: str,
    admission: Optional[StudioAdmission] = None,
) -> PhoneExchangeResponse:
    # The SMS code just proved this phone, which is the author's identity
    # here, so the email-verified flag doesn't gate the tokens.
    return PhoneExchangeResponse(
        author_id=author.id,
        phone_number=phone_number,
        **_exchange_fields(author, admission or StudioAdmission(), can_sign_in=True),
    )


def exchange_phone_token(request: PhoneExchangeRequest) -> PhoneExchangeResponse:
    sms_identity = verify_auth0_sms_token(request.auth0_token)
    with SessionLocal() as db:
        author = get_author_by_phone(db=db, phone_number=sms_identity.phone_number)
        if author is not None:
            if not author.is_verified and not author.email:
                # A phone-only author is verified by the phone. One with an
                # email keeps is_verified for the email, which SMS doesn't prove.
                author.is_verified = True
                author = update_author(db=db, author=author)
            admission = admit_author(db, author, join_link_token=request.join_link_token)
            return _phone_exchange_response(author, sms_identity.phone_number, admission)

        first_name = (request.first_name or "").strip()
        last_name = (request.last_name or "").strip()
        if not first_name or not last_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=PROFILE_NAMES_REQUIRED,
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
        admission = admit_author(db, author, join_link_token=request.join_link_token)
        return _phone_exchange_response(author, sms_identity.phone_number, admission)


def link_phone_identity(backend_token: str, auth0_token: str) -> PhoneLinkResponse:
    try:
        backend_payload = _validate_token(backend_token)
    except jwt.JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid backend token",
        )
    if is_refresh_token_payload(backend_payload):
        # Same rule as validate_and_extract_author_details: a refresh token
        # only mints access tokens at /refresh-token. It must not authorize a
        # change to the author's phone identity.
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


def _google_exchange_response(
    author: Author,
    email: str,
    admission: Optional[StudioAdmission] = None,
) -> GoogleExchangeResponse:
    return GoogleExchangeResponse(
        author_id=author.id,
        email=email,
        **_exchange_fields(author, admission or StudioAdmission(), can_sign_in=bool(author.is_verified)),
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
            admission = admit_author(db, author, join_link_token=request.join_link_token)
            return _google_exchange_response(author, google_identity.email, admission)

        first_name = (request.first_name or google_identity.first_name or "").strip()
        last_name = (request.last_name or google_identity.last_name or "").strip()
        if not first_name or not last_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=PROFILE_NAMES_REQUIRED,
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
        admission = admit_author(db, author, join_link_token=request.join_link_token)
        return _google_exchange_response(author, google_identity.email, admission)


def _email_exchange_response(
    author: Author,
    email: str,
    admission: Optional[StudioAdmission] = None,
) -> EmailExchangeResponse:
    return EmailExchangeResponse(
        author_id=author.id,
        email=email,
        **_exchange_fields(author, admission or StudioAdmission(), can_sign_in=bool(author.is_verified)),
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
            admission = admit_author(db, author, join_link_token=request.join_link_token)
            return _email_exchange_response(author, email_identity.email, admission)

        first_name = (request.first_name or email_identity.first_name or "").strip()
        last_name = (request.last_name or email_identity.last_name or "").strip()
        if not first_name or not last_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=PROFILE_NAMES_REQUIRED,
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
        admission = admit_author(db, author, join_link_token=request.join_link_token)
        return _email_exchange_response(author, email_identity.email, admission)


def login_with_app_account(request: AppLoginRequest) -> AppLoginResponse:
    """Sign in to the Studio with a WeBuddhist app email + password, so app
    users don't have to create a second account.

    The Author is found only through the Users -> Author link
    (Author.user_id). App signup doesn't verify the email, so an app account
    must never be attached here to a separate Studio account that merely
    shares its email - that case is a 409 and the person signs in with the
    Studio account instead.
    """
    with SessionLocal() as db:
        user = get_user_by_email_or_none(db=db, email=request.email)
        if user is None or not user.password or not verify_password(
            plain_password=request.password,
            hashed_password=user.password,
        ):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_EMAIL_PASSWORD)

        author = find_author_by_user_id(db=db, user_id=user.id)
        if author is None:
            email_taken = bool(user.email) and find_author_by_email(db=db, email=user.email) is not None
            phone_taken = bool(user.phone_number) and get_author_by_phone(db=db, phone_number=user.phone_number) is not None
            if email_taken or phone_taken:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=APP_ACCOUNT_CONFLICT)
            author = link_or_create_author_for_user(db=db, user=user)
            if author is None:
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=INVALID_EMAIL_PASSWORD)

        admission = admit_author(db, author, join_link_token=request.join_link_token)
        # The app password proves the app account, which is what this Author
        # is linked to - only a suspension keeps them out now.
        return AppLoginResponse(
            author_id=author.id,
            email=author.email,
            **_exchange_fields(author, admission, can_sign_in=True),
        )
