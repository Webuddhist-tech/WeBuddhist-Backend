from pydantic import BaseModel
from typing import Dict, List, Optional
from uuid import UUID


class TagMetadataDTO(BaseModel):
    id: UUID
    language: str
    name: str
    description: Optional[str] = None


class TagSummaryDTO(BaseModel):
    id: UUID
    name: str
    image: Optional[str] = None
    image_key: Optional[str] = None
    description: Optional[str] = None
    featured: bool = False
    display_order: Optional[int] = None


class TagDTO(TagSummaryDTO):
    plan_ids: List[UUID] = []
    segment_ids: List[str] = []
    metadata: List[TagMetadataDTO] = []


class TagMetadataInput(BaseModel):
    language: str
    name: str
    description: Optional[str] = None
    segment_ids: Optional[List[str]] = None


class CreateTagRequest(BaseModel):
    metadata: List[TagMetadataInput]
    image_key: Optional[str] = None
    featured: bool = False
    display_order: Optional[int] = None
    plan_ids: Optional[List[UUID]] = None
    segment_ids: Optional[List[str]] = None


class UpdateTagRequest(BaseModel):
    metadata: Optional[List[TagMetadataInput]] = None
    image_key: Optional[str] = None
    featured: Optional[bool] = None
    display_order: Optional[int] = None
    plan_ids: Optional[List[UUID]] = None
    segment_ids: Optional[List[str]] = None


class TagsListResponse(BaseModel):
    tags: List[TagDTO]
    skip: int
    limit: int
    total: int


class PublicTagsResponse(BaseModel):
    tags: List[TagSummaryDTO]


class PublicTagsListResponse(BaseModel):
    tags: List[TagSummaryDTO]
    skip: int
    limit: int
    total: int


class SegmentContentDTO(BaseModel):
    segment_id: str
    text_id: str
    content: str


class PublicTagDetailDTO(TagSummaryDTO):
    segments: List[SegmentContentDTO] = []
