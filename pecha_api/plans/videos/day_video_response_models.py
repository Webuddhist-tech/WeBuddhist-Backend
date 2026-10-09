from datetime import datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel


class DayVideoDTO(BaseModel):
    id: UUID
    day_id: UUID
    url: str
    video_id: Optional[str] = None
    title: Optional[str] = None
    duration_seconds: Optional[int] = None
    display_order: int
    created_at: Optional[datetime] = None


class DayVideoListResponse(BaseModel):
    videos: List[DayVideoDTO]


class CreateDayVideoRequest(BaseModel):
    url: str
    title: Optional[str] = None


class DayVideoOrderItem(BaseModel):
    id: UUID
    display_order: int


class ReorderDayVideosRequest(BaseModel):
    videos: List[DayVideoOrderItem]
