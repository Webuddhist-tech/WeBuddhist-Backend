from typing import Optional
from uuid import UUID

from pydantic import BaseModel

from pecha_api.plans.auth.plan_auth_enums import AuthorStatus
from pecha_api.plans.platform_enums import PlatformRole


class AdminAuthorListItemDTO(BaseModel):
    id: UUID
    firstname: str
    lastname: str
    email: Optional[str] = None
    phone_number: Optional[str] = None
    is_verified: bool
    is_active: bool
    platform_role: PlatformRole
    created_at: Optional[str] = None
    # ACTIVE, SUSPENDED, or INACTIVE (never signed in to the Studio).
    account_status: Optional[AuthorStatus] = None


class AdminAuthorListResponse(BaseModel):
    authors: list[AdminAuthorListItemDTO]
    skip: int
    limit: int
    total: int


class AdminAuthorDetailDTO(BaseModel):
    id: UUID
    firstname: str
    lastname: str
    email: Optional[str] = None
    phone_number: Optional[str] = None
    is_verified: bool
    is_active: bool
    platform_role: PlatformRole
    bio: Optional[str] = None
    image_url: Optional[str] = None
    account_status: Optional[AuthorStatus] = None
    suspended_at: Optional[str] = None


class AdminAuthorPlatformRoleUpdate(BaseModel):
    platform_role: PlatformRole


class AdminAuthorActivateResponse(BaseModel):
    id: UUID
    is_active: bool
