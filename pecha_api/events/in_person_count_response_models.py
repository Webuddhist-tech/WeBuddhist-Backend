from datetime import date, datetime
from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field

from pecha_api.plans.media.media_response_models import ImageUrlModel


class InPersonCountDTO(BaseModel):
    """One day's in-person count in the event's group accumulation."""

    id: UUID
    # The day in the event's timezone.
    day: date
    count: int
    created_at: datetime
    updated_at: Optional[datetime] = None


class InPersonCountsResponse(BaseModel):
    items: List[InPersonCountDTO]
    total: int
    skip: int
    limit: int
    # Sum of every in-person count in this group accumulation.
    total_count: int
    # Null when the event has no group accumulation linked.
    group_accumulator_id: Optional[UUID] = None
    # The linked group accumulation the counts are added to, so the Studio
    # can say which one: its title, everyone's total and its target.
    group_accumulator_title: Optional[str] = None
    group_accumulator_total_count: Optional[int] = None
    group_accumulator_target_count: Optional[int] = None
    group_accumulator_image: Optional[ImageUrlModel] = None
    # The timezone days are counted in: the event's, else UTC.
    timezone: str


class CreateInPersonCountRequest(BaseModel):
    day: date
    count: int = Field(ge=1, le=1_000_000_000)


class UpdateInPersonCountRequest(BaseModel):
    count: int = Field(ge=1, le=1_000_000_000)
    # Moves the count to another day; omit to keep its day.
    day: Optional[date] = None
