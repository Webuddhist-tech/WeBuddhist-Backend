from pydantic import BaseModel, Field
from typing import List, Optional
from uuid import UUID


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


class PatchPrayerIntentionRequest(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=64)
    color: Optional[str] = Field(None, min_length=1, max_length=16)
    description: Optional[str] = Field(None, min_length=1)
    display_order: Optional[int] = None
