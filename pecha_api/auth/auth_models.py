from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from pecha_api.auth.auth_enums import RegistrationSource
from pecha_api.utils import Utils


class CreateUserRequest(BaseModel):
    firstname: str
    lastname: str
    email: Optional[str] = None
    password: Optional[str] = None
    phone_number: Optional[str] = None
    avatar_url: Optional[str] = None

    @field_validator("avatar_url", mode="before")
    @classmethod
    def _https_avatar(cls, value: Any) -> Any:
        """Keep only a picture an identity provider serves.

        Social login sends Auth0's profile image here. Anything else is
        dropped, so neither a blank nor a non-URL value is ever stored as the
        user's avatar - and neither is an address on a host of the
        registrant's choosing, which the profile would then hand to everyone
        who views it. Registration is public, so this is the same restriction
        the backfill and profile-update paths apply, at the one remaining
        place an avatar can enter.
        """
        if not isinstance(value, str):
            return None
        picture = value.strip()
        if not Utils.is_social_picture_url(picture):
            return None
        return picture

    @field_validator("email", "password", "phone_number", mode="before")
    @classmethod
    def _blank_to_none(cls, value: Any) -> Any:
        """Treat a blank identifier as absent.

        `email` and `phone_number` are UNIQUE columns, and Postgres exempts
        NULL from a unique index but not ''. A client that sends '' for the
        identifier its user does not have would take the single ''-slot for
        the whole table, and every later caller doing the same collides with
        it and is rejected as an already-existing user.
        """
        if isinstance(value, str) and not value.strip():
            return None
        return value

class CreateSocialUserRequest(BaseModel):
    create_user_request: CreateUserRequest
    platform: RegistrationSource

class UserLoginRequest(BaseModel):
    email: str
    password: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str


class UserInfo(BaseModel):
    name: str
    avatar_url: Optional[str] = None


class UserLoginResponse(BaseModel):
    user: UserInfo
    auth: TokenResponse


class PhoneExchangeRequest(BaseModel):
    auth0_token: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None


class PhoneExchangeResponse(BaseModel):
    user_id: UUID
    phone_number: str
    message: str
    user: UserInfo
    auth: TokenResponse


class PhoneLinkRequest(BaseModel):
    auth0_token: str


class PhoneLinkResponse(BaseModel):
    user_id: UUID
    phone_number: str
    message: str


class RefreshTokenRequest(BaseModel):
    token: str


class RefreshTokenResponse(BaseModel):
    access_token: str
    token_type: str


class PasswordResetRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    password: str

class PropsResponse(BaseModel):
    client_id: str
    domain: str
    audience: str