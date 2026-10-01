from pydantic import BaseModel, ConfigDict, field_validator
from uuid import UUID
from typing import List, Optional, Union
from datetime import datetime

from pecha_api.bookmarks.bookmark_enums import BookmarkType
from pecha_api.plans.series.series_response_models import SeriesMetadataResponse, SeriesProgressDTO


class BookmarkSegmentDTO(BaseModel):
    id: str
    content: str


class BookmarkTextDTO(BaseModel):
    id: str
    title: str
    segment: Optional[BookmarkSegmentDTO] = None


class PlanBookmarkMetadataDTO(BaseModel):
    title: str
    description: str
    language: str


class BookmarkPlanDTO(BaseModel):
    id: UUID
    metadata: Optional[PlanBookmarkMetadataDTO] = None
    image: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None


class BookmarkSeriesDTO(BaseModel):
    id: UUID
    metadata: SeriesMetadataResponse = None
    image: Optional[str] = None
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    progress: Optional[SeriesProgressDTO] = None


class BookmarkAccumulatorDTO(BaseModel):
    id: UUID
    title: str
    image: Optional[str] = None


class BookmarkTimerDTO(BaseModel):
    id: UUID
    title: str
    duration: int
    ambient_sound_name: Optional[str] = None
    bell_at_start: bool = True
    bell_at_end: bool = True


class BookmarkRecitationCollectionDTO(BaseModel):
    id: UUID
    title: str
    image: Optional[str] = None
    item_count: int


class BookmarkGroupAccumulatorDTO(BaseModel):
    id: UUID
    group_id: UUID
    title: str
    image: Optional[str] = None


class BookmarkGroupRecitationCollectionDTO(BaseModel):
    id: UUID
    group_id: UUID
    title: str
    image: Optional[str] = None
    item_count: int


SOURCE_ID_UUID_EXEMPT_TYPES = (BookmarkType.VERSE, BookmarkType.TEXT)


class CreateBookmarkRequest(BaseModel):
    type: BookmarkType
    source_id: str
    name: Optional[str] = None

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str, info) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source_id must not be empty")

        bookmark_type = info.data.get("type")
        if bookmark_type is not None and bookmark_type not in SOURCE_ID_UUID_EXEMPT_TYPES:
            try:
                return str(UUID(value))
            except ValueError:
                raise ValueError(f"source_id must be a valid UUID for type {bookmark_type.value}")
        return value


class BookmarkDTO(BaseModel):
    model_config = ConfigDict(ser_json_exclude_none=True)

    id: UUID
    type: BookmarkType
    source_id: str
    name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    text: Optional[BookmarkTextDTO] = None
    plan: Optional[BookmarkPlanDTO] = None
    series: Optional[BookmarkSeriesDTO] = None
    accumulator: Optional[BookmarkAccumulatorDTO] = None
    timer: Optional[BookmarkTimerDTO] = None
    recitation_collection: Optional[BookmarkRecitationCollectionDTO] = None
    group_recitation_collection: Optional[BookmarkGroupRecitationCollectionDTO] = None
    group_accumulator: Optional[BookmarkGroupAccumulatorDTO] = None


class BookmarksResponse(BaseModel):
    model_config = ConfigDict(ser_json_exclude_none=True)

    bookmarks: List[BookmarkDTO]
    total: int
    skip: int
    limit: int


class BookmarkExistsQuery(BaseModel):
    type: Optional[BookmarkType] = None
    source_id: str

    @field_validator("source_id")
    @classmethod
    def _validate_source_id(cls, value: str, info) -> str:
        value = value.strip()
        if not value:
            raise ValueError("source_id must not be empty")

        bookmark_type = info.data.get("type")
        if bookmark_type is not None and bookmark_type not in SOURCE_ID_UUID_EXEMPT_TYPES:
            try:
                return str(UUID(value))
            except ValueError:
                raise ValueError(f"source_id must be a valid UUID for type {bookmark_type.value}")
        return value


class BookmarkExistsResponse(BaseModel):
    exists: bool
    id: Optional[UUID] = None
