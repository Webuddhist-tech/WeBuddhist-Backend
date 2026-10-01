from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, field_validator

from pecha_api.plans.plans_enums import LanguageCode
from pecha_api.poems.enums import PoemStatus


class PoemDTO(BaseModel):
    """DTO for a single poem with presigned image URL."""
    id: UUID
    title: str
    content: str
    author_name: str
    chapter_name: Optional[str] = None
    language: str
    image_url: Optional[str] = None
    status: str
    published_at: Optional[str] = None
    created_at: str
    updated_at: str


class PoemsResponse(BaseModel):
    """Response for list poems endpoints."""
    poems: List[PoemDTO]
    skip: int
    limit: int
    total: int
    seed: Optional[str] = None


class CreatePoemRequest(BaseModel):
    """Request to create a new poem."""
    title: str
    content: str
    author_name: str
    chapter_name: Optional[str] = None
    language: LanguageCode = LanguageCode.EN
    image_key: Optional[str] = None
    status: PoemStatus = PoemStatus.DRAFT

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("title must not be empty")
        return value.strip()

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("content must not be empty")
        return value.strip()

    @field_validator("author_name")
    @classmethod
    def validate_author_name(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("author_name must not be empty")
        return value.strip()


class UpdatePoemRequest(BaseModel):
    """Request to update a poem (partial update)."""
    title: Optional[str] = None
    content: Optional[str] = None
    author_name: Optional[str] = None
    chapter_name: Optional[str] = None
    language: Optional[LanguageCode] = None
    image_key: Optional[str] = None
    status: Optional[PoemStatus] = None

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("title must not be empty")
        return value.strip() if value else None

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("content must not be empty")
        return value.strip() if value else None

    @field_validator("author_name")
    @classmethod
    def validate_author_name(cls, value: Optional[str]) -> Optional[str]:
        if value is not None and not value.strip():
            raise ValueError("author_name must not be empty")
        return value.strip() if value else None
