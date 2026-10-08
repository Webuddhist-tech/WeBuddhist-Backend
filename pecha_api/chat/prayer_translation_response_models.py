from typing import Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class PrayerTranslationPayloadResponse(BaseModel):
    message_id: UUID
    body: str


class PrayerTranslationResultRequest(BaseModel):
    body_at_dispatch: str = Field(
        ...,
        description="Prayer body when the worker started; must match current row to apply.",
    )
    source_language: Optional[str] = None
    translations: Optional[Dict[str, str]] = None
    failed: bool = False
