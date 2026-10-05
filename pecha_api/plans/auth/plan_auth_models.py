from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pecha_api.plans.auth.plan_auth_enums import AuthorStatus

class CreateAuthorRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    password: str

class AuthorDetails(BaseModel):
    first_name: str
    last_name: str
    email: str
    status: AuthorStatus
    message: str

class AuthorResponse(BaseModel):
    author: AuthorDetails

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class AuthorInfo(BaseModel):
    name: str
    image_url: Optional[str] = None


class AuthorLoginResponse(BaseModel):
    user: AuthorInfo
    auth: TokenResponse
    # Groups this sign-in put the author in (accepted invites, or the join
    # link's group) - the Studio can open the first one.
    joined_group_ids: List[UUID] = []
    # Set when a join_link_token was sent but couldn't be used; the sign-in
    # itself still succeeded.
    join_link_error: Optional[str] = None


class PhoneExchangeRequest(BaseModel):
    auth0_token: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    # From a /join?link= page: joins that group on the way in.
    join_link_token: Optional[str] = None


class PhoneExchangeResponse(BaseModel):
    author_id: UUID
    phone_number: str
    status: AuthorStatus
    # ACTIVE or SUSPENDED. `status` stays ACTIVE/INACTIVE so existing
    # Studio checks keep working.
    account_status: Optional[AuthorStatus] = None
    message: str
    user: AuthorInfo
    auth: Optional[TokenResponse] = None
    joined_group_ids: List[UUID] = []
    join_link_error: Optional[str] = None


class PhoneLinkRequest(BaseModel):
    auth0_token: str


class PhoneLinkResponse(BaseModel):
    author_id: UUID
    phone_number: str
    message: str


class GoogleExchangeRequest(BaseModel):
    auth0_token: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    # From a /join?link= page: joins that group on the way in.
    join_link_token: Optional[str] = None


class GoogleExchangeResponse(BaseModel):
    author_id: UUID
    email: str
    status: AuthorStatus
    # ACTIVE or SUSPENDED. `status` stays ACTIVE/INACTIVE so existing
    # Studio checks keep working.
    account_status: Optional[AuthorStatus] = None
    message: str
    user: AuthorInfo
    auth: Optional[TokenResponse] = None
    joined_group_ids: List[UUID] = []
    join_link_error: Optional[str] = None


class EmailExchangeRequest(BaseModel):
    auth0_token: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    # From a /join?link= page: joins that group on the way in.
    join_link_token: Optional[str] = None


class EmailExchangeResponse(BaseModel):
    author_id: UUID
    email: str
    status: AuthorStatus
    # ACTIVE or SUSPENDED. `status` stays ACTIVE/INACTIVE so existing
    # Studio checks keep working.
    account_status: Optional[AuthorStatus] = None
    message: str
    user: AuthorInfo
    auth: Optional[TokenResponse] = None
    joined_group_ids: List[UUID] = []
    join_link_error: Optional[str] = None


class AuthorLoginRequest(BaseModel):
    email: str
    password: str
    # From a /join?invite= page: proves the email, so an account whose email
    # was never confirmed can sign in and accept.
    invite_token: Optional[str] = None
    join_link_token: Optional[str] = None

class TokenPayload(BaseModel):
    email: str
    iss: str
    aud: str
    iat: datetime
    exp: datetime
    typ: str

class AuthorVerificationResponse(BaseModel):
    email: str
    status: AuthorStatus
    message: str
    account_status: Optional[AuthorStatus] = None
    joined_group_ids: List[UUID] = []

class ResponseError(BaseModel):
    error: str
    message: str

class PasswordResetRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    token: str
    password: str

class EmailReVerificationResponse(BaseModel):
    message: str

class RefreshTokenRequest(BaseModel):
    token: str

class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: str

class InviteRegisterRequest(BaseModel):
    """One-step sign-up from an emailed group invite: no verify-email round
    trip, and the invite is accepted."""
    invite_token: str
    first_name: str
    last_name: str
    password: str


class AppLoginRequest(BaseModel):
    """Sign in to the Studio with a WeBuddhist app email + password."""
    email: str
    password: str
    join_link_token: Optional[str] = None


class AppLoginResponse(BaseModel):
    author_id: UUID
    email: Optional[str] = None
    status: AuthorStatus
    account_status: Optional[AuthorStatus] = None
    message: str
    user: AuthorInfo
    auth: Optional[TokenResponse] = None
    joined_group_ids: List[UUID] = []
    join_link_error: Optional[str] = None
