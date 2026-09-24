from datetime import datetime
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from pecha_api.plans.groups.groups_enums import (
    AuthorGroupInviteStatus,
    AuthorGroupJoinRequestStatus,
    AuthorGroupMemberRole,
    AuthorGroupStatus,
    AuthorGroupType,
)
from pecha_api.plans.groups.group_summary_models import (
    AuthorGroupSummaryDTO,
    GroupMetadataDTO,
    GroupMetadataResponse,
)
from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.plans.plans_response_models import PlanDTO
from pecha_api.plans.series.series_response_models import SeriesListItemDTO
from pecha_api.plans.tags.tag_response_models import TagSummaryDTO
from pecha_api.group_accumulator.group_accumulator_response_models import GroupAccumulatorDTO
from pecha_api.group_recitation_collection.response_models import GroupRecitationCollectionDTO

# Removing a joined user from a group blocks them from rejoining. The moderator
# may pick a different length, but this is what Studio sends when they don't.
DEFAULT_GROUP_BAN_DURATION_DAYS = 7
MAX_GROUP_BAN_DURATION_DAYS = 365


class GroupSeriesListItemDTO(SeriesListItemDTO):
    is_group_enrolled: Optional[bool] = None

__all__ = [
    "AuthorGroupSummaryDTO",
    "GroupMetadataDTO",
    "GroupMetadataResponse",
    "GroupMetadataInput",
    "GroupSocialLinkInput",
    "GroupSocialLinkDTO",
    "AuthorGroupMemberDTO",
    "AuthorGroupDetailDTO",
    "AuthorGroupListResponse",
    "CreateAuthorGroupRequest",
    "UpdateAuthorGroupRequest",
    "UpdateAuthorGroupStatusRequest",
    "ReplaceGroupTagsRequest",
    "GroupSeriesListItemDTO",
    "ReplaceGroupSeriesRequest",
    "ReplaceGroupPlansRequest",
    "ReplaceGroupSocialLinksRequest",
    "CreateGroupInviteRequest",
    "GroupInviteDTO",
    "GroupInviteListResponse",
    "GroupInviteCreatedResponse",
    "CreateGroupJoinRequest",
    "GroupJoinRequestDTO",
    "GroupJoinRequestUserDTO",
    "GroupJoinRequestListResponse",
    "UpdateGroupMemberRoleRequest",
    "TransferGroupOwnershipRequest",
    "GroupMantraAccumulationDTO",
    "GroupAccumulationsResponse",
    "GroupMemberAccumulationDTO",
    "GroupMemberAccumulationsResponse",
    "AuthorGroupMemberProfileDTO",
    "AuthorGroupMembersListResponse",
    "GroupPracticeType",
    "GroupPracticeCardDTO",
    "GroupPracticesResponse",
    "GroupPracticeFeedItemDTO",
    "GroupPracticesFeedResponse",
    "GroupPermissionDTO",
]


class GroupMetadataInput(BaseModel):
    title: str
    sub_title: Optional[str] = None
    description: Optional[str] = None
    description_long: Optional[str] = None
    language: LanguageCode


class GroupSocialLinkInput(BaseModel):
    platform: str
    url: str


class GroupSocialLinkDTO(BaseModel):
    id: UUID
    platform: str
    url: str


class AuthorGroupMemberDTO(BaseModel):
    author_id: UUID
    role: AuthorGroupMemberRole
    firstname: str
    lastname: str
    email: str


class AuthorGroupDetailDTO(BaseModel):
    id: UUID
    slug: str
    group_type: AuthorGroupType
    is_public: bool
    status: AuthorGroupStatus = AuthorGroupStatus.DRAFT
    avatar_key: Optional[str] = None
    banner_key: Optional[str] = None
    avatar_url: Optional[str] = None
    banner_url: Optional[str] = None
    metadata: GroupMetadataResponse = []
    members: List[AuthorGroupMemberDTO] = []
    tags: List[TagSummaryDTO] = []
    social_links: List[GroupSocialLinkDTO] = []
    series: List[GroupSeriesListItemDTO] = []
    plans: List[PlanDTO] = []
    follower_count: int = 0
    joiner_count: int = 0


class PublicAuthorGroupSummaryDTO(AuthorGroupSummaryDTO):
    tags: List[str] = []
    # None when the caller is anonymous or has never requested to join.
    my_join_request_status: Optional[AuthorGroupJoinRequestStatus] = None


class PublicAuthorGroupDetailDTO(AuthorGroupDetailDTO):
    tags: List[str] = []
    my_join_request_status: Optional[AuthorGroupJoinRequestStatus] = None
    # The group chat room this caller can open, so the app can go straight to
    # it from the group page. None when the caller is anonymous, is neither a
    # joiner nor a follower, or nobody has started the chat yet.
    chat_room_id: Optional[UUID] = None


class AuthorGroupListResponse(BaseModel):
    groups: List[AuthorGroupSummaryDTO]
    skip: int
    limit: int
    total: int


class PublicAuthorGroupListResponse(BaseModel):
    groups: List[PublicAuthorGroupSummaryDTO]
    skip: int
    limit: int
    total: int


class UserFollowedAuthorGroupDTO(BaseModel):
    id: UUID
    avatar_key: Optional[str] = None
    avatar_url: Optional[str] = None
    metadata: GroupMetadataResponse = []
    follower_count: int = 0
    tags: List[str] = []


class UserJoinedAuthorGroupDTO(BaseModel):
    id: UUID
    avatar_key: Optional[str] = None
    avatar_url: Optional[str] = None
    metadata: GroupMetadataResponse = []
    joiner_count: int = 0
    tags: List[str] = []


class UserFollowedAuthorGroupListResponse(BaseModel):
    groups: List[UserFollowedAuthorGroupDTO]
    skip: int
    limit: int
    total: int


class UserJoinedAuthorGroupListResponse(BaseModel):
    groups: List[UserJoinedAuthorGroupDTO]
    skip: int
    limit: int
    total: int


class CreateAuthorGroupRequest(BaseModel):
    slug: str
    group_type: AuthorGroupType = AuthorGroupType.PAGE
    is_public: bool = True
    avatar_key: Optional[str] = None
    banner_key: Optional[str] = None
    metadata: List[GroupMetadataInput]

    @field_validator("metadata")
    @classmethod
    def validate_metadata_not_empty(cls, value: List[GroupMetadataInput]):
        if not value:
            raise ValueError("At least one metadata entry is required")
        return value


class UpdateAuthorGroupRequest(BaseModel):
    slug: Optional[str] = None
    is_public: Optional[bool] = None
    avatar_key: Optional[str] = None
    banner_key: Optional[str] = None
    metadata: Optional[List[GroupMetadataInput]] = None


class UpdateAuthorGroupStatusRequest(BaseModel):
    """Separate from UpdateAuthorGroupRequest so a settings edit can never
    publish or hide a group."""

    status: AuthorGroupStatus


class ReplaceGroupTagsRequest(BaseModel):
    tag_ids: List[UUID]


class ReplaceGroupSeriesRequest(BaseModel):
    series_ids: List[UUID]


class ReplaceGroupPlansRequest(BaseModel):
    plan_ids: List[UUID]


class ReplaceGroupSocialLinksRequest(BaseModel):
    social_links: List[GroupSocialLinkInput]


class CreateGroupInviteRequest(BaseModel):
    target_email: str
    role: AuthorGroupMemberRole


class GroupInviteDTO(BaseModel):
    id: UUID
    group_id: UUID
    group_name: str
    target_email: str
    role: AuthorGroupMemberRole
    status: AuthorGroupInviteStatus
    expires_at: datetime
    accepted_at: Optional[datetime] = None
    rejected_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    created_at: datetime
    created_by: str
    inviter_name: str
    inviter_email: str


class GroupInviteListResponse(BaseModel):
    invites: List[GroupInviteDTO]
    total: int


class GroupInviteCreatedResponse(BaseModel):
    invite: GroupInviteDTO
    notification_id: Optional[UUID] = None


class CreateGroupJoinRequest(BaseModel):
    message: Optional[str] = Field(default=None, max_length=1000)


class GroupJoinRequestDTO(BaseModel):
    id: UUID
    status: AuthorGroupJoinRequestStatus


class GroupJoinRequestUserDTO(BaseModel):
    id: UUID
    user_id: UUID
    user_name: str
    email: Optional[str] = None
    user_avatar_url: Optional[str] = None
    message: Optional[str] = None
    status: AuthorGroupJoinRequestStatus
    created_at: datetime


class GroupJoinRequestListResponse(BaseModel):
    requests: List[GroupJoinRequestUserDTO]
    skip: int
    limit: int
    total: int


class UpdateGroupMemberRoleRequest(BaseModel):
    role: AuthorGroupMemberRole


class TransferGroupOwnershipRequest(BaseModel):
    new_owner_author_id: UUID


class GroupMantraAccumulationDTO(BaseModel):
    mantra_id: UUID
    mantra_slug: Optional[str] = None
    mantra_title: Optional[str] = None
    count: int


class GroupAccumulationsResponse(BaseModel):
    group_id: UUID
    mantras: List[GroupMantraAccumulationDTO]
    total_count: int
    total: int
    skip: int
    limit: int


class GroupMemberAccumulationDTO(BaseModel):
    username: Optional[str] = None
    fullname: str
    avatar_url: Optional[str] = None
    count: int


class GroupMemberAccumulationsResponse(BaseModel):
    total_members: int
    list: List[GroupMemberAccumulationDTO]
    skip: int
    limit: int


class AuthorGroupMemberProfileDTO(BaseModel):
    user_id: UUID
    # None when the caller may not see staff roles (private group, not joined).
    role: Optional[str] = None
    username: Optional[str] = None
    fullname: str
    avatar_url: Optional[str] = None


class AuthorGroupMembersListResponse(BaseModel):
    total_members: int
    list: List[AuthorGroupMemberProfileDTO]
    skip: int
    limit: int


class GroupPracticeType(str, Enum):
    SERIES = "series"
    ACCUMULATOR = "accumulator"
    COLLECTION = "collection"
    PLAN = "plan"


class GroupPracticeCardDTO(BaseModel):
    type: GroupPracticeType
    series: Optional[GroupSeriesListItemDTO] = None
    accumulator: Optional[GroupAccumulatorDTO] = None
    collection: Optional[GroupRecitationCollectionDTO] = None


class GroupPracticesResponse(BaseModel):
    practices: List[GroupPracticeCardDTO]
    skip: int
    limit: int
    total: int


class GroupPracticeFeedItemDTO(BaseModel):
    type: GroupPracticeType
    practice_at: datetime
    is_joined: bool
    group_id: UUID
    group_name: Optional[str] = None
    group_slug: Optional[str] = None
    group_avatar_url: Optional[str] = None
    series: Optional[GroupSeriesListItemDTO] = None
    accumulator: Optional[GroupAccumulatorDTO] = None
    plan: Optional[PlanDTO] = None
    collection: Optional[GroupRecitationCollectionDTO] = None


class GroupPracticesFeedResponse(BaseModel):
    practices: List[GroupPracticeFeedItemDTO]
    skip: int
    limit: int
    total: int
    include_unfollowed: bool


class GroupPermissionDTO(BaseModel):
    group_id: UUID
    has_permission: bool
    can_create_content: bool
    role: Optional[AuthorGroupMemberRole] = None
    is_super_admin: bool
    author_id: Optional[UUID] = None


class GroupJoinedUserDTO(BaseModel):
    """A community user who joined the group, as listed in Studio.

    Unlike the public `AuthorGroupMemberProfileDTO` this carries `user_id`,
    because Studio needs it to act on the user (remove/ban).
    """

    user_id: UUID
    username: Optional[str] = None
    fullname: str
    avatar_url: Optional[str] = None
    joined_at: Optional[datetime] = None


class GroupJoinedUsersListResponse(BaseModel):
    users: List[GroupJoinedUserDTO]
    skip: int
    limit: int
    total: int


class RemoveGroupUserRequest(BaseModel):
    """Remove a joined user and block them from rejoining for a while."""

    ban_duration_days: int = Field(
        default=DEFAULT_GROUP_BAN_DURATION_DAYS,
        ge=1,
        le=MAX_GROUP_BAN_DURATION_DAYS,
        description=(
            "How many days the user is blocked from rejoining. "
            f"Defaults to {DEFAULT_GROUP_BAN_DURATION_DAYS}."
        ),
    )
    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional note shown to other moderators in the banned list.",
    )

    @field_validator("reason")
    @classmethod
    def _strip_reason(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class GroupBanDTO(BaseModel):
    id: UUID
    user_id: UUID
    username: Optional[str] = None
    fullname: str
    avatar_url: Optional[str] = None
    reason: Optional[str] = None
    expires_at: datetime
    lifted_at: Optional[datetime] = None
    created_at: datetime
    is_active: bool


class GroupBanListResponse(BaseModel):
    bans: List[GroupBanDTO]
    skip: int
    limit: int
    total: int
