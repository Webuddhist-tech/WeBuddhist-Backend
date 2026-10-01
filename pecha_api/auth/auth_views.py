from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from ..db import database
from ..users.users_models import Users
from starlette import status
from .auth_service import authenticate_and_generate_tokens, refresh_access_token, register_user_with_source, \
    request_reset_password, update_password, create_user, exchange_phone_token, link_phone_identity, \
    remember_social_avatar, is_trusted_social_register_caller
from .auth_models import CreateUserRequest, UserLoginRequest, RefreshTokenRequest, PasswordResetRequest, \
    ResetPasswordRequest, UserLoginResponse, RefreshTokenResponse, CreateSocialUserRequest, \
    PhoneExchangeRequest, PhoneExchangeResponse, PhoneLinkRequest, PhoneLinkResponse
from .auth_enums import RegistrationSource
from typing import Annotated, Optional

oauth2_scheme = HTTPBearer()
auth_router = APIRouter(
    prefix="/auth",
    tags=["Authentications"],
)


def get_db():
    db = database.SessionLocal()
    try:
        yield db
    finally:
        db.close()


@auth_router.post("/register", status_code=status.HTTP_201_CREATED)
def register_user(create_user_request: CreateUserRequest) -> UserLoginResponse:
    registration_source = RegistrationSource.EMAIL
    return register_user_with_source(
        create_user_request=create_user_request,
        registration_source=registration_source
    )

# `response_model=None`: the annotation says what the function hands back, and
# `Users` is a SQLAlchemy model rather than a shape FastAPI can build a response
# model from. The body is unchanged - the encoder serialises the row as before.
@auth_router.post("/social_register", status_code=status.HTTP_201_CREATED, response_model=None)
def register_user(
    create_social_user_request: CreateSocialUserRequest,
    x_social_register_token: Annotated[Optional[str], Header(alias="X-Social-Register-Token")] = None,
) -> Users:
    registration_source = RegistrationSource.EMAIL
    if create_social_user_request.platform:
        registration_source =  create_social_user_request.platform
    try:
        return create_user(
            create_user_request=create_social_user_request.create_user_request,
            registration_source=registration_source
        )
    except HTTPException as exc:
        # The Auth0 action calls this on every login. After the first one the
        # user already exists, and that 409 is how the action knows to stop.
        # The picture still has to land, or an account created before this
        # field existed never shows the Auth0 photo.
        #
        # Writing to an account the caller has not proved anything about is
        # the dangerous half of that: the route is public, so without the
        # shared secret anyone knowing an email could post it back with a
        # picture of their choosing and have it replace that user's avatar.
        if exc.status_code == status.HTTP_409_CONFLICT and is_trusted_social_register_caller(
            x_social_register_token
        ):
            remember_social_avatar(create_social_user_request.create_user_request)
        raise

@auth_router.post("/login", status_code=status.HTTP_200_OK)
def login_user(user_login_request: UserLoginRequest) -> UserLoginResponse:
    return authenticate_and_generate_tokens(
        email=user_login_request.email,
        password=user_login_request.password
    )


@auth_router.post("/phone/exchange", status_code=status.HTTP_200_OK)
def phone_exchange(request: PhoneExchangeRequest) -> PhoneExchangeResponse:
    return exchange_phone_token(request)


@auth_router.post("/phone/link", status_code=status.HTTP_200_OK)
def phone_link(
    request: PhoneLinkRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> PhoneLinkResponse:
    return link_phone_identity(
        backend_token=authentication_credential.credentials,
        auth0_token=request.auth0_token,
    )


@auth_router.post("/refresh-token", status_code=status.HTTP_200_OK)
def refresh_token(refresh_token_request: RefreshTokenRequest) -> RefreshTokenResponse:
    return refresh_access_token(refresh_token_request.token)


@auth_router.post("/request-reset-password", status_code=status.HTTP_202_ACCEPTED)
def password_reset_request(reset_request: PasswordResetRequest):
    request_reset_password(email=reset_request.email)


@auth_router.post("/reset-password", status_code=status.HTTP_200_OK)
def password_reset(reset_password_request: ResetPasswordRequest,
                   authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]):
    update_password(token=authentication_credential.credentials, password=reset_password_request.password)
