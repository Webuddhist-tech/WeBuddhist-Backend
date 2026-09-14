from pydantic import BaseModel, ConfigDict, model_validator
from typing import Optional, List
from datetime import datetime
from pecha_api.plans.plans_enums import (
    DifficultyLevel,
    PlanStatus,
    ContentType,
    PlanAudioType,
    MonlamVoiceName,
)
from uuid import UUID
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.shared.subtask_reference_resolver import SubTaskReferenceDTO
from pecha_api.plans.tags.tag_response_models import TagSummaryDTO


class CreatePlanRequest(BaseModel):
    title: str
    description: str
    difficulty_level: DifficultyLevel
    total_days: int
    language: str
    group_id: UUID
    image_url: Optional[str] = None
    tag_ids: Optional[List[UUID]] = []
    start_date: Optional[datetime] = None
    series_id: Optional[UUID] = None
    display_order: Optional[int] = None

class UpdatePlanRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    language: Optional[str] = None
    difficulty_level: Optional[DifficultyLevel] = None
    total_days: Optional[int] = None
    image_url: Optional[str] = None
    tag_ids: Optional[List[UUID]] = None
    start_date: Optional[datetime] = None
    series_id: Optional[UUID] = None
    display_order: Optional[int] = None

class GeneratePlanAudioRequest(BaseModel):
    day_id: Optional[UUID] = None
    sub_task_id: Optional[UUID] = None
    language: str
    type: Optional[PlanAudioType] = PlanAudioType.TEXT_READING
    voice_name: MonlamVoiceName = MonlamVoiceName.DOLKAR_LHASA_FEMALE

    @model_validator(mode="after")
    def validate_either_day_or_subtask(self):
        if not self.day_id and not self.sub_task_id:
            raise ValueError("Either day_id or sub_task_id must be provided")
        if self.day_id and self.sub_task_id:
            raise ValueError("Provide either day_id or sub_task_id, not both")
        return self

class PlanStatusUpdate(BaseModel):
    status: PlanStatus

class AuthorDTO(BaseModel):
    id: UUID
    firstname: str
    lastname: str
    image_url: Optional[str] = None 
    image_key: Optional[str] = None  

class PlanDTO(BaseModel):
    id: UUID
    title: str
    description: str
    language: str
    difficulty_level: Optional[DifficultyLevel] = None
    image_url: Optional[str] = None
    image_key: Optional[str] = None
    total_days: int
    tags: List[TagSummaryDTO] = []
    status: PlanStatus
    featured: Optional[bool] = False
    subscription_count: int
    author: Optional[AuthorDTO] = None
    start_date: Optional[datetime] = None
    series_id: Optional[UUID] = None
    display_order: Optional[int] = None
    group_id: Optional[UUID] = None

class SubTaskDTO(BaseModel):
    id: UUID
    content_type: ContentType
    content: Optional[str] = None
    display_order: Optional[int] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None
    audio_url: Optional[str] = None
    reference_id: Optional[UUID] = None
    reference: Optional[SubTaskReferenceDTO] = None

class TaskDTO(BaseModel):
    id: UUID
    title: Optional[str] = None
    estimated_time: Optional[int] = None
    display_order: Optional[int] = None
    subtasks: List[SubTaskDTO] = []

class DayVideoSummaryDTO(BaseModel):
    id: UUID
    url: str
    video_id: Optional[str] = None
    title: Optional[str] = None
    display_order: int

class PlanDayDTO(BaseModel):
    id: UUID
    day_number: int
    tasks: List[TaskDTO]
    audio_url: Optional[str] = None
    audio_duration_ms: Optional[int] = None
    audio_key: Optional[str] = None
    has_audio: Optional[bool] = None
    thumbnail_url: Optional[str] = None
    thumbnail_key: Optional[str] = None
    shareable_image_url: Optional[str] = None
    shareable_image_key: Optional[str] = None
    videos: List[DayVideoSummaryDTO] = []


class PlanVideoSummaryDTO(BaseModel):
    id: UUID
    url: str
    video_id: Optional[str] = None
    title: Optional[str] = None
    display_order: int


class PlanWithDays(BaseModel):
    id: UUID
    title: str
    description: str            
    language: str
    image_url: Optional[str] = None
    plan_image_url: Optional[str] = None
    total_days: int
    difficulty_level: str
    tags: List[TagSummaryDTO] = []
    status: PlanStatus
    days: List[PlanDayDTO]
    videos: List[PlanVideoSummaryDTO] = []
    start_date: Optional[datetime] = None
    series_id: Optional[UUID] = None
    display_order: Optional[int] = None
    group_id: Optional[UUID] = None

class PlansResponse(BaseModel):
    plans: List[PlanDTO]
    skip: int
    limit: int
    total: int

class PlanWithAggregates(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)
    plan: Plan
    total_days: int
    subscription_count: int

class PlansRepositoryResponse(BaseModel):
    plan_info: List[PlanWithAggregates]
    total: int

TaskDTO.model_rebuild()
