from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Union
from pecha_api.plans.plans_enums import DifficultyLevel, PlanStatus,ContentType
from uuid import UUID
from datetime import datetime, date as DateType
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.shared.subtask_reference_resolver import SubTaskReferenceDTO
from pecha_api.plans.tags.tag_response_models import TagSummaryDTO
from pecha_api.plans.series.series_response_models import SeriesProgressDTO

class PlanDayBasic(BaseModel):
    id: str
    day_number: int

class ImageUrlModel(BaseModel):
    thumbnail: str
    medium: str
    original: str       

class PlanDaysResponse(BaseModel):
    days: List[PlanDayBasic]

class AuthorDTO(BaseModel):
    id: UUID
    firstname: str
    lastname: str
    image: Optional[ImageUrlModel] = None


    
class PlanVideoSummaryDTO(BaseModel):
    id: UUID
    url: str
    video_id: Optional[str] = None
    title: Optional[str] = None
    display_order: int


class PublicPlanDTO(BaseModel):
    id: UUID
    title: str
    description: str
    language: str
    difficulty_level: Optional[DifficultyLevel] = None
    image: Optional[ImageUrlModel] = None
    total_days: int
    tags: list[TagSummaryDTO] = []
    author: Optional[AuthorDTO] = None
    videos: List[PlanVideoSummaryDTO] = []
    start_date: Optional[datetime] = None
    display_order: Optional[int] = None
    group_id: Optional[UUID] = None
    series_id: Optional[UUID] = None  # Set when the plan is part of a series

class SubTaskDTO(BaseModel):
    id: UUID
    content_type: ContentType
    content: Optional[str] = None
    duration: Optional[str] = None
    image_url: Optional[str] = None
    audio_url: Optional[str] = None
    source_text_id: Optional[str] = None
    pecha_segment_id: Optional[str] = None
    segment_ids: Optional[List[str]] = None
    segment_numbers: Optional[List[int]] = None
    reference_id: Optional[UUID] = None
    reference: Optional[SubTaskReferenceDTO] = None
    display_order: Optional[int] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None

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
    thumbnail_url: Optional[str] = None
    shareable_image_url: Optional[str] = None
    videos: List[DayVideoSummaryDTO] = []
    series_id: Optional[UUID] = None  # Set when the plan is part of a series


class PlanDayCacheCleanupResponse(BaseModel):
    plan_id: UUID
    day_number: Optional[int] = None
    keys_deleted: int


class PlanWithDays(BaseModel):
    id: UUID
    title: str
    description: str            
    language: str
    image: Optional[ImageUrlModel] = None
    plan_image: Optional[ImageUrlModel] = None
    total_days: int
    difficulty_level: str
    tags: List[TagSummaryDTO] = []
    days: List[PlanDayDTO]

class PublicPlansResponse(BaseModel):
    plans: List[PublicPlanDTO]
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

class SeriesMetadataDTO(BaseModel):
    id: UUID
    title: str
    sub_title: Optional[str] = None
    description: Optional[str] = None
    language: str


SeriesMetadataResponse = Union[SeriesMetadataDTO, List[SeriesMetadataDTO], None]


class SeriesDTO(BaseModel):
    id: UUID
    metadata: SeriesMetadataResponse = []
    image: Optional[ImageUrlModel] = None
    progress: Optional[SeriesProgressDTO] = None

class DailyPlanResponse(BaseModel):
    plan_id: UUID
    plan_title: str
    plan_description: str
    image: Optional[ImageUrlModel] = None
    series: Optional[SeriesDTO] = None
    date: DateType
    day_number: int
    total_days: int
    start_date: DateType
    end_date: DateType
    previous_date: Optional[DateType] = None
    next_date: Optional[DateType] = None
    previous_plan_id: Optional[UUID] = None
    next_plan_id: Optional[UUID] = None
    audio_url: Optional[str] = None
    audio_duration_ms: Optional[int] = None
    tasks: List[TaskDTO]

class TagsResponse(BaseModel):
    tags: List[TagSummaryDTO]
    
TaskDTO.model_rebuild()
