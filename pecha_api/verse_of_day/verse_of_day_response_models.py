from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from uuid import UUID
import datetime


# Type alias for verses dictionary by language
VersesDict = Dict[str, str]


class GroupInfoDTO(BaseModel):
    """DTO for group metadata information."""
    id: UUID
    title: str
    sub_title: Optional[str] = None
    description: Optional[str] = None
    language: str

    class Config:
        from_attributes = True


class VerseMetadataDTO(BaseModel):
    """DTO for individual verse metadata entry."""
    lang: str
    verse: str

    class Config:
        from_attributes = True


class VerseOfDayDTO(BaseModel):
    id: UUID
    verses: Optional[VersesDict] = None
    image_urls: Optional[List[str]] = None
    verse_id: Optional[str] = None
    ref_id: Optional[str] = None
    source: Optional[str] = None
    ref_type: Optional[str] = None
    group_id: Optional[UUID] = None
    date: datetime.date

    class Config:
        from_attributes = True


class VerseOfDayResponse(BaseModel):
    verse_of_day: VerseOfDayDTO


class VerseOfDayPublicDTO(BaseModel):
    id: UUID
    verses: Optional[VersesDict] = None
    verse: Optional[str] = None
    image_url: Optional[str] = None  
    ref_id: Optional[str] = None
    source: Optional[str] = None
    ref_type: Optional[str] = None
    date: datetime.date
    group_id: Optional[UUID] = None
    group_info: Optional[List[GroupInfoDTO]] = None

    class Config:
        from_attributes = True


class VerseOfDayPublicResponse(BaseModel):
    verse_of_day: Optional[VerseOfDayPublicDTO] = None


class VerseOfDayListResponse(BaseModel):
    """Response for listing multiple verses of day."""
    verses: List[VerseOfDayPublicDTO]
    total: int


class CreateVerseOfDayRequest(BaseModel):
    """Request to create verse of day with multilingual verses."""
    verses: VersesDict
    image_urls: Optional[List[str]] = None
    verse_id: Optional[str] = None
    ref_id: Optional[str] = None
    source: Optional[str] = Field(default=None, max_length=255)
    ref_type: Optional[str] = None
    group_id: Optional[UUID] = None
    date: datetime.date


class UpdateVerseOfDayRequest(BaseModel):
    verses: Optional[VersesDict] = None
    image_urls: Optional[List[str]] = None
    verse_id: Optional[str] = None
    ref_id: Optional[str] = None
    source: Optional[str] = Field(default=None, max_length=255)
    ref_type: Optional[str] = None
    group_id: Optional[UUID] = None
    date: Optional[datetime.date] = None
