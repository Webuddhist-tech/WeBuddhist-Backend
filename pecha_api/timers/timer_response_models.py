from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
from uuid import UUID
from .timer_enums import TimerType


class TimerDTO(BaseModel):
    id: UUID
    user_id: UUID
    group_id: Optional[UUID] = None
    type: TimerType
    name: str
    description: Optional[str] = None
    duration: int
    audio_url: Optional[str] = None
    image_url: Optional[str] = None
    ambient_sound_id: Optional[UUID] = None
    bell_at_start: bool
    bell_at_end: bool
    parent_preset_id: Optional[UUID] = None
    created_at: datetime
    updated_at: Optional[datetime] = None


class TimersResponse(BaseModel):
    timers: List[TimerDTO]
    total: int
    skip: int
    limit: int


class CreateTimerRequest(BaseModel):
    group_id: Optional[UUID] = None
    name: str
    description: Optional[str] = None
    duration: int
    audio_url: Optional[str] = None
    image_url: Optional[str] = None
    ambient_sound_id: Optional[UUID] = None
    bell_at_start: bool = True
    bell_at_end: bool = True
    parent_preset_id: Optional[UUID] = None


class UpdateTimerRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    duration: Optional[int] = None
    audio_url: Optional[str] = None
    image_url: Optional[str] = None
    ambient_sound_id: Optional[UUID] = None
    bell_at_start: Optional[bool] = None
    bell_at_end: Optional[bool] = None


class RecordTimerStopRequest(BaseModel):
    timer_id: UUID
    duration: int


class RecordTimerStopResponse(BaseModel):
    timer_id: UUID
    name: str
    duration_ms: int


class TimerSessionDTO(BaseModel):
    duration: int
    created_at: datetime


class TimerHistoryDTO(BaseModel):
    timer_id: UUID
    name: str
    description: Optional[str] = None
    actual_duration: int
    total_time_spent: int
    sessions: List[TimerSessionDTO]


class TimerHistoryResponse(BaseModel):
    timers: List[TimerHistoryDTO]
    total: int
    skip: int
    limit: int
