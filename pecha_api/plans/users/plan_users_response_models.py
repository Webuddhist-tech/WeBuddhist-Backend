from typing import List, Optional
from pydantic import BaseModel
from pecha_api.plans.media.media_response_models import ImageUrlModel
from uuid import UUID
from datetime import datetime
from pecha_api.plans.plans_enums import ContentType, SeriesStatus
from pecha_api.plans.shared.subtask_reference_resolver import SubTaskReferenceDTO
from pecha_api.plans.tags.tag_response_models import TagSummaryDTO
from pecha_api.plans.groups.group_summary_models import AuthorGroupSummaryDTO
from pecha_api.plans.public.plan_response_models import DayVideoSummaryDTO
from pecha_api.plans.series.series_response_models import SeriesProgressDTO, SeriesPartnerDTO



class UserPlanEnrollRequest(BaseModel):
    plan_id: UUID


class UserPlanStatus(BaseModel):
    status: str  # not_started, active, paused, completed, abandoned


class UserPlanDayCompletionStatus(BaseModel):
    day_number: int
    is_completed: bool

class UserPlanDayCompletionStatusResponse(BaseModel):
    days: List[UserPlanDayCompletionStatus]
    start_date: Optional[datetime] = None

class UserPlanProgressResponse(BaseModel):
    id: UUID
    user_id: UUID
    plan_id: UUID
    plan: dict  # Will contain plan details
    started_at: datetime
    streak_count: int
    longest_streak: int
    status: str
    is_completed: bool
    completed_at: Optional[datetime] = None
    created_at: datetime

class EnrolledUserPlan(BaseModel):
    user_id: UUID
    plan_id: UUID
    streak_count: int
    longest_streak: int
    status: str
    created_at: datetime
    is_completed: bool

class UserPlanDTO(BaseModel):
    id: UUID
    title: str
    description: str
    language: str
    difficulty_level: str
    image: Optional[ImageUrlModel] = None
    started_at: Optional[datetime] = None
    total_days: int
    tags: list[TagSummaryDTO] = []
    start_date: Optional[datetime] = None
    display_order: Optional[int] = None
    group: Optional[AuthorGroupSummaryDTO] = None


class UserPlansResponse(BaseModel):
    plans: List[UserPlanDTO]
    skip: int
    limit: int
    total: int


class UserPlanProgressUpdate(BaseModel):
    status: str

class UserSubTaskDTO(BaseModel):
    id: UUID
    display_order: Optional[int] = None
    is_completed: bool
    duration: Optional[str] = None
    content_type: ContentType
    content: Optional[str] = None
    audio_url: Optional[str] = None
    source_text_id: Optional[str] = None
    pecha_segment_id: Optional[str] = None
    segment_ids: Optional[List[str]] = None
    segment_numbers: Optional[List[int]] = None
    reference_id: Optional[UUID] = None
    reference: Optional[SubTaskReferenceDTO] = None
    start_ms: Optional[int] = None
    end_ms: Optional[int] = None

class UserTaskDTO(BaseModel):
    id: UUID
    title: str
    estimated_time: Optional[int] = None
    display_order: int
    is_completed: bool
    sub_tasks: List[UserSubTaskDTO] = []

class UserPlanDayDetailsResponse(BaseModel):
    id: UUID
    day_number: int
    tasks: List[UserTaskDTO]
    is_completed: bool
    audio_url: Optional[str] = None
    audio_duration_ms: Optional[int] = None
    thumbnail_url: Optional[str] = None
    shareable_image_url: Optional[str] = None
    videos: List[DayVideoSummaryDTO] = []


# Series Enrollment Models

class UserSeriesEnrollRequest(BaseModel):
    series_id: UUID
    group_id: Optional[UUID] = None
    auto_enroll_next: Optional[bool] = True
    start_immediately: Optional[bool] = False


class UserSeriesEnrollmentDTO(BaseModel):
    id: UUID
    user_id: UUID
    series_id: UUID
    series_title: str
    series_description: Optional[str] = None
    image: Optional[ImageUrlModel] = None
    enrolled_at: datetime
    status: str  # ACTIVE, PAUSED, COMPLETED, CANCELLED
    auto_enroll_next: bool
    current_plan_id: Optional[UUID] = None
    current_plan_title: Optional[str] = None
    is_completed: bool
    completed_at: Optional[datetime] = None
    total_plans: int
    completed_plans: int
    progress_percentage: float
    enrolled_count: int = 0
    group: Optional[AuthorGroupSummaryDTO] = None
    series_partner_id: Optional[UUID] = None  # Partner group ID when enrolled via a partner group
    progress: Optional[SeriesProgressDTO] = None
    partner: Optional[SeriesPartnerDTO] = None


class UserSeriesEnrollmentsResponse(BaseModel):
    enrollments: List[UserSeriesEnrollmentDTO]
    skip: int
    limit: int
    total: int


class UserSeriesProgressResponse(BaseModel):
    id: UUID
    series_id: UUID
    series_title: str
    series_description: Optional[str] = None
    enrolled_at: datetime
    status: str
    auto_enroll_next: bool
    current_plan_id: Optional[UUID] = None
    is_completed: bool
    completed_at: Optional[datetime] = None
    plans: List[UserPlanDTO]  # All plans in series with completion status
    enrolled_count: int = 0
    group: Optional[AuthorGroupSummaryDTO] = None
    progress: Optional[SeriesProgressDTO] = None
    partner: Optional[SeriesPartnerDTO] = None


class UpdateSeriesEnrollmentRequest(BaseModel):
    auto_enroll_next: Optional[bool] = None
    status: Optional[SeriesStatus] = None


class UserSeriesDaysCompletedDTO(BaseModel):
    series_id: UUID
    series_title: str
    series_description: Optional[str] = None
    image: Optional[ImageUrlModel] = None
    days_completed: int
    enrolled_count: int = 0
    group: Optional[AuthorGroupSummaryDTO] = None
    progress: Optional[SeriesProgressDTO] = None
    partner: Optional[SeriesPartnerDTO] = None


class UserSeriesDaysCompletedResponse(BaseModel):
    series: List[UserSeriesDaysCompletedDTO]
    skip: int
    limit: int
    total: int