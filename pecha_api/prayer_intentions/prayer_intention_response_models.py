from pydantic import BaseModel
from typing import List


class PrayerIntentionDTO(BaseModel):
    slug: str
    label: str
    color: str
    description: str
    display_order: int


class PrayerIntentionsResponse(BaseModel):
    intentions: List[PrayerIntentionDTO]
