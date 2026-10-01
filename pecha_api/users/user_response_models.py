import re
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator
from .users_enums import SocialProfile
from .reserved_usernames import is_reserved_username

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9](?:[a-zA-Z0-9_.-]{1,28}[a-zA-Z0-9])?$")

class SocialMediaProfile(BaseModel):
    account: SocialProfile
    url: str

class UserInfoRequest(BaseModel):
    firstname: str
    lastname: str
    title: Optional[str] = None
    organization: Optional[str] = None
    location: Optional[str] = None
    educations: List[str]
    avatar_url : Optional[str] = None
    about_me: Optional[str] = None
    social_profiles: List[SocialMediaProfile]

class UserInfoResponse(BaseModel):
    id: UUID
    firstname: str
    lastname: str
    username: str
    email: Optional[str] = None
    title: Optional[str] = None
    organization: Optional[str] = None
    location: Optional[str] = None
    educations: List[str]
    avatar_url: Optional[str] = None
    about_me: Optional[str] = None
    followers: int
    following: int
    social_profiles: List[SocialMediaProfile]

class PublisherInfoResponse(BaseModel):
    id: str
    username: str
    firstname: str
    lastname: str
    avatar_url: Optional[str] = None


class UpdateUsernameRequest(BaseModel):
    username: str

    @field_validator("username")
    @classmethod
    def username_must_be_valid(cls, v: str) -> str:
        if re.search(r"\s", v):
            raise ValueError("Username cannot contain spaces")
        v = v.strip()
        if not v:
            raise ValueError("Username cannot be empty")
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        if len(v) > 30:
            raise ValueError("Username must be at most 30 characters")
        if not USERNAME_PATTERN.match(v):
            raise ValueError(
                "Username can only contain letters, numbers, underscores, hyphens, and periods, "
                "and must start and end with a letter or number"
            )
        v = v.lower()
        if is_reserved_username(v):
            raise ValueError("This username is reserved and cannot be used")
        return v


class UpdateUsernameResponse(BaseModel):
    message: str
    username: Optional[str] = None
    suggestions: Optional[List[str]] = None


class OnboardingStatusResponse(BaseModel):
    has_seen_onboarding: bool


class UpdateOnboardingStatusRequest(BaseModel):
    has_seen_onboarding: bool
