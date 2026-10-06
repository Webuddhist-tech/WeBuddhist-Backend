from typing import List, Optional, Union
from uuid import UUID

from pydantic import BaseModel

from pecha_api.plans.groups.groups_enums import (
    AuthorGroupMemberRole,
    AuthorGroupStatus,
    AuthorGroupType,
)
from pecha_api.plans.tags.tag_response_models import TagSummaryDTO


class GroupMetadataDTO(BaseModel):
    id: UUID
    title: str
    sub_title: Optional[str] = None
    description: Optional[str] = None
    description_long: Optional[str] = None
    language: str


GroupMetadataResponse = Union[GroupMetadataDTO, List[GroupMetadataDTO], None]


class GroupTraditionDTO(BaseModel):
    id: UUID
    code: str
    # Localized to the request language, falling back to EN.
    name: Optional[str] = None


class AuthorGroupSummaryDTO(BaseModel):
    id: UUID
    slug: str
    group_type: AuthorGroupType
    is_public: bool
    status: AuthorGroupStatus = AuthorGroupStatus.DRAFT
    avatar_key: Optional[str] = None
    banner_key: Optional[str] = None
    avatar_url: Optional[str] = None
    banner_url: Optional[str] = None
    tradition: Optional[GroupTraditionDTO] = None
    metadata: GroupMetadataResponse = []
    tags: List[TagSummaryDTO] = []
    follower_count: int = 0
    joiner_count: int = 0
    member_count: int = 0
    # Current CMS author's membership role in this group (null when not a member).
    my_role: Optional[AuthorGroupMemberRole] = None
