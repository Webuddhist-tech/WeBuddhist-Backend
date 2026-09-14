from pydantic import BaseModel, Field, model_validator
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from enum import Enum

from pecha_api.plans.media.media_response_models import ImageUrlModel
from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.accumulator.accumulator_enums import GroupAccumulatorLinkType


class GroupAccumulatorMemberSortBy(str, Enum):
    TOTAL = "total"
    TODAY = "today"


class GroupAccumulatorMetadataDTO(BaseModel):
    language: LanguageCode
    description: Optional[str] = None


class GroupAccumulatorLinkRequest(BaseModel):
    """`link_type` and `video_id` are derived server-side from the URL."""
    url: str
    title: Optional[str] = None


class GroupAccumulatorLinkDTO(BaseModel):
    id: UUID
    url: str
    link_type: GroupAccumulatorLinkType
    video_id: Optional[str] = Field(
        None,
        description="YouTube video id; null when link_type is LINK",
    )
    title: Optional[str] = None
    display_order: int


def _validate_metadata_languages(metadata: Optional[List[GroupAccumulatorMetadataDTO]]):
    if metadata is None:
        return
    languages = [entry.language for entry in metadata]
    if len(languages) != len(set(languages)):
        raise ValueError("metadata languages must be unique")


class CreateGroupAccumulatorRequest(BaseModel):
    accumulator_id: Optional[UUID] = None
    title: Optional[str] = None
    image_key: Optional[str] = None
    target_count: Optional[int] = Field(None, ge=1)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    metadata: Optional[List[GroupAccumulatorMetadataDTO]] = Field(
        None,
        description="Per-language About text. Replaces the full set; [] clears it.",
    )
    links: Optional[List[GroupAccumulatorLinkRequest]] = Field(
        None,
        description="Ordered links. Replaces the full set; [] clears it. Array index becomes display_order.",
    )

    @model_validator(mode="after")
    def validate_metadata(self):
        _validate_metadata_languages(self.metadata)
        return self


class UpdateGroupAccumulatorRequest(BaseModel):
    accumulator_id: Optional[UUID] = None
    title: Optional[str] = None
    image_key: Optional[str] = None
    target_count: Optional[int] = Field(None, ge=1)
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    metadata: Optional[List[GroupAccumulatorMetadataDTO]] = Field(
        None,
        description="Per-language About text. Replaces the full set; [] clears it. Omit to leave unchanged.",
    )
    links: Optional[List[GroupAccumulatorLinkRequest]] = Field(
        None,
        description="Ordered links. Replaces the full set; [] clears it. Omit to leave unchanged.",
    )

    @model_validator(mode="after")
    def validate_metadata(self):
        _validate_metadata_languages(self.metadata)
        return self


class GroupAccumulatorDTO(BaseModel):
    id: UUID
    preset_accumulator_id: Optional[UUID] = Field(
        None,
        description="ID of the linked preset accumulator, if any",
    )
    text_id: Optional[str] = Field(
        None,
        description="Text ID from the linked preset accumulator, if any",
    )
    mantra_id: Optional[UUID] = Field(
        None,
        description="Mantra ID from the linked preset accumulator, if any",
    )
    group_id: UUID
    title: Optional[str] = None
    image: Optional[ImageUrlModel] = None
    image_key: Optional[str] = None
    target_count: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    description: Optional[str] = Field(
        None,
        description="About text resolved for the requested language, falling back to EN",
    )
    metadata: Optional[List[GroupAccumulatorMetadataDTO]] = Field(
        None,
        description="All per-language About entries. Returned on CMS reads only.",
    )
    is_joined: Optional[bool] = Field(
        None,
        description="Whether the authenticated user has joined (null when unauthenticated)",
    )
    member_count: int = Field(
        0,
        description="Number of users who joined this group accumulator",
    )
    created_at: datetime
    updated_at: Optional[datetime] = None


class GroupAccumulatorsResponse(BaseModel):
    accumulators: List[GroupAccumulatorDTO]
    total: int
    skip: int
    limit: int


class SubmitGroupCountRequest(BaseModel):
    current_count: int = Field(..., ge=0, description="User's new absolute current count")


class GroupAccumulatorHistoryItemDTO(BaseModel):
    id: Optional[UUID] = Field(None, description="History entry ID. None if no history was created (e.g., zero delta)")
    user_id: UUID
    count: int
    created_at: datetime


class GroupAccumulatorDetailUserDTO(BaseModel):
    total_count: int = Field(..., description="Authenticated user's count for the active session")
    today_count: int = Field(..., description="Authenticated user's count for today in the request timezone")
    username: Optional[str] = None
    image: Optional[str] = Field(None, description="Presigned URL for the user's avatar")
    fullname: str = Field(..., description="User's display name")


class GroupAccumulatorDetailDTO(BaseModel):
    id: UUID
    preset_accumulator_id: Optional[UUID] = Field(
        None,
        description="ID of the linked preset accumulator, if any",
    )
    text_id: Optional[str] = Field(
        None,
        description="Text ID from the linked preset accumulator, if any",
    )
    mantra_id: Optional[UUID] = Field(
        None,
        description="Mantra ID from the linked preset accumulator, if any",
    )
    group_id: UUID
    title: Optional[str] = None
    image: Optional[ImageUrlModel] = None
    image_key: Optional[str] = None
    target_count: Optional[int] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    description: Optional[str] = Field(
        None,
        description="About text resolved for the requested language, falling back to EN",
    )
    metadata: Optional[List[GroupAccumulatorMetadataDTO]] = Field(
        None,
        description="All per-language About entries. Returned on CMS reads only.",
    )
    links: List[GroupAccumulatorLinkDTO] = Field(
        default_factory=list,
        description="Links shared by the group, ordered by display_order",
    )
    total_count: int = Field(..., description="Total lifetime count from all users")
    total_today_count: int = Field(0, description="Total count from all users for today in the request timezone")
    user: Optional[GroupAccumulatorDetailUserDTO] = Field(
        None,
        description="Authenticated user's profile and counts (null when unauthenticated)",
    )
    is_joined: Optional[bool] = Field(
        None,
        description="Whether the authenticated user has joined (null when unauthenticated)",
    )
    member_count: int = Field(0, description="Number of users who joined this group accumulator")
    created_at: datetime
    updated_at: Optional[datetime] = None


class GroupAccumulatorHistoryResponse(BaseModel):
    group_accumulator: GroupAccumulatorDetailDTO
    history: List[GroupAccumulatorHistoryItemDTO]
    total: int
    skip: int
    limit: int


class GroupAccumulatorMemberDTO(BaseModel):
    user_id: UUID
    username: Optional[str] = None
    fullname: str
    avatar_url: Optional[str] = None
    joined_at: datetime
    total_count: int = Field(0, description="Member's lifetime contribution count")
    today_count: int = Field(0, description="Member's contribution count for today in the request timezone")


class GroupAccumulatorMembersResponse(BaseModel):
    members: List[GroupAccumulatorMemberDTO]
    member_count: int = Field(..., description="Total number of users who joined this group accumulator")
    total: int
    skip: int
    limit: int


class GroupAccumulatorContributionDTO(BaseModel):
    id: UUID
    count: int
    created_at: datetime


class GroupAccumulatorUserSessionDTO(BaseModel):
    id: UUID = Field(..., description="User participation session ID")
    is_active: bool = Field(..., description="True when this is the user's current non-reset session")
    total_counted: int = Field(..., description="Total count contributed during this session")
    created_at: datetime
    deleted_at: Optional[datetime] = Field(None, description="When the user reset this session")
    contributions: List[GroupAccumulatorContributionDTO] = Field(
        default_factory=list,
        description="Individual count submissions during this session",
    )


class GroupAccumulatorUserSessionsResponse(BaseModel):
    group_accumulator: GroupAccumulatorDTO
    sessions: List[GroupAccumulatorUserSessionDTO]
    total: int
    skip: int
    limit: int
