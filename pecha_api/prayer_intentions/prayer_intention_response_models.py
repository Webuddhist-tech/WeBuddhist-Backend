from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from .intention_slugs import LEGACY_PRAYER_INTENTION_SLUG_ALIASES


class PrayerIntentionDTO(BaseModel):
    slug: str
    label: str
    color: str
    description: str
    display_order: int


class PrayerIntentionsResponse(BaseModel):
    intentions: List[PrayerIntentionDTO]


class PrayerIntentionCMSDTO(PrayerIntentionDTO):
    id: UUID
    linked_event_count: int = Field(
        0,
        description="How many events restrict prayers to this intention",
    )


class PrayerIntentionsCMSListResponse(BaseModel):
    intentions: List[PrayerIntentionCMSDTO]


class CreatePrayerIntentionRequest(BaseModel):
    slug: str = Field(..., min_length=1, max_length=32)
    label: str = Field(..., min_length=1, max_length=64)
    color: str = Field(..., min_length=1, max_length=16)
    description: str = Field(..., min_length=1)
    display_order: int = 0

    @field_validator("slug", "label", "color", "description", mode="before")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        if isinstance(value, str):
            value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value

    @field_validator("slug")
    @classmethod
    def normalize_slug(cls, value: str) -> str:
        slug = value.lower()
        # Posting maps these former names onto the current intentions, so an
        # intention created under one would be offered to an event but never
        # matched when a prayer is posted with it.
        if slug in LEGACY_PRAYER_INTENTION_SLUG_ALIASES:
            raise ValueError(
                f"'{slug}' is a former intention name and is reserved; "
                f"use a different slug"
            )
        return slug


class PatchPrayerIntentionRequest(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=64)
    color: Optional[str] = Field(None, min_length=1, max_length=16)
    description: Optional[str] = Field(None, min_length=1)
    display_order: Optional[int] = None

    @field_validator("label", "color", "description", mode="before")
    @classmethod
    def strip_optional_text(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not isinstance(value, str):
            return value
        value = value.strip()
        if not value:
            raise ValueError("must not be blank")
        return value
