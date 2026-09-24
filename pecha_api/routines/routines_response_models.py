from pydantic import BaseModel, Field, field_validator, model_serializer, model_validator
from typing import Any, Optional, List, Self
from uuid import UUID
from datetime import datetime

from pecha_api.plans.media.media_response_models import ImageUrlModel
from .routines_enums import SessionType


def _normalize_optional_title(value: Any) -> Any:
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return value


class SessionRequest(BaseModel):
    session_type: SessionType
    # str, not UUID: RECITATION sessions can hold a non-UUID pecha-style text id.
    source_id: Optional[str] = None
    accumulator_id: Optional[UUID] = Field(
        None,
        description="Preset accumulator id from GET /accumulators/presets (stored as source_id)",
    )
    group_accumulator_id: Optional[UUID] = Field(
        None,
        description="Group accumulator id from GET /group-accumulators (stored as source_id)",
    )
    duration_ms: Optional[int] = None
    display_order: int

    @field_validator("source_id", mode="before")
    @classmethod
    def _stringify_source_id(cls, value: Any) -> Any:
        return str(value) if isinstance(value, UUID) else value

    @model_validator(mode="after")
    def resolve_accumulator_fields(self) -> Self:
        if self.session_type == SessionType.ACCUMULATOR:
            if self.accumulator_id is not None and self.source_id is None:
                self.source_id = str(self.accumulator_id)
            elif self.source_id is not None and self.accumulator_id is None:
                self.accumulator_id = UUID(self.source_id)
        elif self.session_type == SessionType.GROUP_ACCUMULATOR:
            if self.group_accumulator_id is not None and self.source_id is None:
                self.source_id = str(self.group_accumulator_id)
            elif self.source_id is not None and self.group_accumulator_id is None:
                self.group_accumulator_id = UUID(self.source_id)
        return self

    @model_validator(mode="after")
    def validate_source_id_format(self) -> Self:
        if self.source_id is not None and self.session_type != SessionType.RECITATION:
            try:
                UUID(self.source_id)
            except ValueError as exc:
                raise ValueError(
                    f"source_id must be a valid UUID for session_type {self.session_type}"
                ) from exc
        return self


class CreateTimeBlockRequest(BaseModel):
    time: str
    time_int: int
    title: Optional[str] = Field(
        None, max_length=255, description="Optional practice name for this time block"
    )
    notification_enabled: bool = True
    sessions: List[SessionRequest]

    @field_validator("title", mode="before")
    @classmethod
    def _normalize_title(cls, value: Any) -> Any:
        return _normalize_optional_title(value)


class UpdateTimeBlockRequest(BaseModel):
    time: str
    time_int: int
    # Intended: PUT replaces the whole time block, so an omitted title clears the
    # stored one — the same semantics as notification_enabled below, and the only
    # way to remove a title. Callers already send time/time_int/sessions on every
    # update, so the client always has the full block (title included) in hand.
    title: Optional[str] = Field(
        None, max_length=255, description="Optional practice name for this time block"
    )
    notification_enabled: bool = True
    sessions: List[SessionRequest]

    @field_validator("title", mode="before")
    @classmethod
    def _normalize_title(cls, value: Any) -> Any:
        return _normalize_optional_title(value)


class RoutineFirstSegmentDTO(BaseModel):
    id: str
    content: str


class SessionDTO(BaseModel):
    id: UUID
    session_type: SessionType
    # str, not UUID: RECITATION sessions can hold a non-UUID pecha-style text id.
    source_id: Optional[str] = None
    accumulator_id: Optional[UUID] = Field(
        None,
        description="Preset accumulator id (same id returned by GET /accumulators/presets)",
    )
    group_accumulator_id: Optional[UUID] = Field(
        None,
        description="Group accumulator id (same id returned by GET /group-accumulators)",
    )
    title: Optional[str] = None
    language: Optional[str] = None  
    duration_ms: Optional[int] = None  
    image: Optional[ImageUrlModel] = None    
    display_order: int
    start_date: Optional[datetime] = None  # Plan's start_date
    started_at: Optional[datetime] = None  # User's started_at from progress
    item_count: Optional[int] = None  # Recitation collection's item count
    current_plan_id: Optional[UUID] = None  # SERIES: plan active for today's date
    current_plan_title: Optional[str] = None  # SERIES: title of the active plan
    first_segment: Optional[RoutineFirstSegmentDTO] = None

    @model_serializer(mode="wrap")
    def _omit_inapplicable_fields(self, serializer):
        data = serializer(self)
        if self.session_type == SessionType.TIMER:
            for field in (
                "source_id",
                "accumulator_id",
                "group_accumulator_id",
                "title",
                "language",
                "image",
                "start_date",
                "started_at",
                "item_count",
                "current_plan_id",
                "current_plan_title",
                "first_segment",
            ):
                data.pop(field, None)
        elif self.session_type in (
            SessionType.RECITATION_COLLECTION,
            SessionType.GROUP_RECITATION_COLLECTION,
        ):
            for field in (
                "duration_ms",
                "language",
                "start_date",
                "started_at",
                "current_plan_id",
                "current_plan_title",
                "accumulator_id",
                "group_accumulator_id",
                "first_segment",
            ):
                data.pop(field, None)
        elif self.session_type == SessionType.RECITATION:
            for field in (
                "duration_ms",
                "start_date",
                "started_at",
                "item_count",
                "current_plan_id",
                "current_plan_title",
                "accumulator_id",
                "group_accumulator_id",
            ):
                data.pop(field, None)
        elif self.session_type == SessionType.ACCUMULATOR:
            accumulator_id = self.accumulator_id or self.source_id
            if accumulator_id is not None:
                data["accumulator_id"] = accumulator_id
            data.pop("source_id", None)
            for field in (
                "duration_ms",
                "start_date",
                "started_at",
                "item_count",
                "current_plan_id",
                "current_plan_title",
                "group_accumulator_id",
                "first_segment",
            ):
                data.pop(field, None)
        elif self.session_type == SessionType.GROUP_ACCUMULATOR:
            group_accumulator_id = self.group_accumulator_id or self.source_id
            if group_accumulator_id is not None:
                data["group_accumulator_id"] = group_accumulator_id
            data.pop("source_id", None)
            for field in (
                "duration_ms",
                "start_date",
                "started_at",
                "item_count",
                "current_plan_id",
                "current_plan_title",
                "accumulator_id",
                "first_segment",
            ):
                data.pop(field, None)
        elif self.session_type == SessionType.PLAN:
            for field in (
                "duration_ms",
                "item_count",
                "current_plan_id",
                "current_plan_title",
                "accumulator_id",
                "group_accumulator_id",
                "first_segment",
            ):
                data.pop(field, None)
        else:  # SERIES exposes start_date / started_at and current plan fields
            for field in (
                "duration_ms",
                "item_count",
                "accumulator_id",
                "group_accumulator_id",
                "first_segment",
            ):
                data.pop(field, None)
        return data


class TimeBlockDTO(BaseModel):
    id: UUID
    time: str
    time_int: int
    title: Optional[str] = None
    notification_enabled: bool
    sessions: List[SessionDTO]


class RoutineWithTimeBlocksResponse(BaseModel):
    id: UUID
    time_blocks: List[TimeBlockDTO]


class RoutineResponse(BaseModel):
    id: UUID
    time_blocks: List[TimeBlockDTO]
    skip: int
    limit: int
    total: int


class RoutineInfoResponse(BaseModel):
    series_count: int
    recitation_count: int
