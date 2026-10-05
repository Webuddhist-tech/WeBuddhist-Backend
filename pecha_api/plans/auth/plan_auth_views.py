from typing import Annotated

from fastapi import APIRouter, Depends
from starlette import status

from pecha_api.plans.auth.cms_auth_deps import get_cms_author_token
from pecha_api.plans.groups.groups_response_models import GroupInvitePreviewDTO, GroupJoinLinkPreviewDTO
from pecha_api.plans.groups.groups_service import get_invite_preview
from pecha_api.plans.groups.join_links_service import get_join_link_preview
from .plan_auth_models import (
    AppLoginRequest,
    AppLoginResponse,
    AuthorDetails,
    AuthorLoginRequest,
    AuthorLoginResponse,
    AuthorVerificationResponse,
    CreateAuthorRequest,
    EmailReVerificationResponse,
    InviteRegisterRequest,
    PasswordResetRequest,
    PhoneExchangeRequest,
    PhoneExchangeResponse,
    PhoneLinkRequest,
    PhoneLinkResponse,
    GoogleExchangeRequest,
    GoogleExchangeResponse,
    EmailExchangeRequest,
    EmailExchangeResponse,
    RefreshTokenRequest,
    RefreshTokenResponse,
    ResetPasswordRequest,
)
from .plan_auth_services import (
    authenticate_and_generate_tokens,
    exchange_email_token,
    exchange_google_token,
    exchange_phone_token,
    link_phone_identity,
    login_with_app_account,
    refresh_access_token,
    register_author,
    register_author_from_invite,
    re_verify_email,
    request_reset_password,
    update_password,
    verify_author_email,
)

plan_auth_router = APIRouter(
    prefix="/cms/auth",
    tags=["CMS Plan Authentications"],
)


@plan_auth_router.post("/register", status_code=status.HTTP_202_ACCEPTED, response_model=AuthorDetails)
def register_user(create_user_request: CreateAuthorRequest) -> AuthorDetails:
    return register_author(create_user_request=create_user_request)


@plan_auth_router.get("/verify-email", status_code=status.HTTP_200_OK)
def verify_email(token: Annotated[str, Depends(get_cms_author_token)]) -> AuthorVerificationResponse:
    return verify_author_email(token=token)


@plan_auth_router.post("/email-re-verification", status_code=status.HTTP_202_ACCEPTED, response_model=EmailReVerificationResponse)
def email_re_verification(email: str):
    return re_verify_email(email=email)


@plan_auth_router.post("/login", status_code=status.HTTP_200_OK)
def login_user(author_login_request: AuthorLoginRequest) -> AuthorLoginResponse:
    return authenticate_and_generate_tokens(
        email=author_login_request.email,
        password=author_login_request.password,
        invite_token=author_login_request.invite_token,
        join_link_token=author_login_request.join_link_token,
    )


@plan_auth_router.get("/invites/preview", status_code=status.HTTP_200_OK, response_model=GroupInvitePreviewDTO)
def invite_preview(token: str) -> GroupInvitePreviewDTO:
    return get_invite_preview(invite_token=token)


@plan_auth_router.post("/invites/register", status_code=status.HTTP_201_CREATED, response_model=AuthorLoginResponse)
def invite_register(request: InviteRegisterRequest) -> AuthorLoginResponse:
    return register_author_from_invite(request)


@plan_auth_router.get("/join-links/preview", status_code=status.HTTP_200_OK, response_model=GroupJoinLinkPreviewDTO)
def join_link_preview(token: str) -> GroupJoinLinkPreviewDTO:
    return get_join_link_preview(link_token=token)


@plan_auth_router.post("/app/login", status_code=status.HTTP_200_OK, response_model=AppLoginResponse)
def app_login(request: AppLoginRequest) -> AppLoginResponse:
    return login_with_app_account(request)


@plan_auth_router.post("/phone/exchange", status_code=status.HTTP_200_OK)
def phone_exchange(request: PhoneExchangeRequest) -> PhoneExchangeResponse:
    return exchange_phone_token(request)


@plan_auth_router.post("/google/exchange", status_code=status.HTTP_200_OK)
def google_exchange(request: GoogleExchangeRequest) -> GoogleExchangeResponse:
    return exchange_google_token(request)


@plan_auth_router.post("/email/exchange", status_code=status.HTTP_200_OK)
def email_exchange(request: EmailExchangeRequest) -> EmailExchangeResponse:
    return exchange_email_token(request)


@plan_auth_router.post("/phone/link", status_code=status.HTTP_200_OK)
def phone_link(
    request: PhoneLinkRequest,
    backend_token: Annotated[str, Depends(get_cms_author_token)],
) -> PhoneLinkResponse:
    return link_phone_identity(
        backend_token=backend_token,
        auth0_token=request.auth0_token,
    )


@plan_auth_router.post("/request-reset-password", status_code=status.HTTP_202_ACCEPTED)
async def password_reset_request(reset_request: PasswordResetRequest):
    return request_reset_password(email=reset_request.email)


@plan_auth_router.post("/reset-password", status_code=status.HTTP_200_OK)
def password_reset(reset_password_request: ResetPasswordRequest):
    update_password(token=reset_password_request.token, password=reset_password_request.password)


@plan_auth_router.post("/refresh-token", status_code=status.HTTP_200_OK)
def refresh_token(refresh_token_request: RefreshTokenRequest) -> RefreshTokenResponse:
    return refresh_access_token(refresh_token_request.token)
