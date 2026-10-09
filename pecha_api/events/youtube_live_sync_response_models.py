from datetime import datetime
from typing import List, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_RUN_TIMES = 12
MAX_EVENTS_PER_REQUEST = 100


def normalize_run_time(value: str) -> str:
    """"8:30" -> "08:30"; anything that is not a 24-hour HH:MM is rejected."""
    parts = value.strip().split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError(f"'{value}' is not a time of day in HH:MM form")
    hour, minute = int(parts[0]), int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"'{value}' is not a valid time of day")
    return f"{hour:02d}:{minute:02d}"


def _dedupe(values: List[UUID]) -> List[UUID]:
    return list(dict.fromkeys(values))


class UpdateYoutubeLiveSyncRequest(BaseModel):
    """Sets the same schedule on each of the chosen events. Events not listed
    are left exactly as they are."""

    event_ids: List[UUID] = Field(
        min_length=1,
        max_length=MAX_EVENTS_PER_REQUEST,
        description="The events of this group to schedule.",
    )
    enabled: bool = True
    run_times: List[str] = Field(
        default_factory=list,
        description='Times of day to check the channel, "HH:MM" (24-hour), read in `timezone`.',
    )
    timezone: Optional[str] = Field(
        default=None,
        description="IANA timezone the run times are in. Defaults to the platform event timezone.",
    )

    @field_validator("event_ids")
    @classmethod
    def validate_event_ids(cls, values: List[UUID]) -> List[UUID]:
        return _dedupe(values)

    @field_validator("run_times")
    @classmethod
    def validate_run_times(cls, values: List[str]) -> List[str]:
        normalized = sorted({normalize_run_time(value) for value in values})
        if len(normalized) > MAX_RUN_TIMES:
            raise ValueError(f"at most {MAX_RUN_TIMES} run times are allowed")
        return normalized

    @field_validator("timezone")
    @classmethod
    def validate_timezone(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not value.strip():
            return None
        cleaned = value.strip()
        if cleaned.upper() == "UTC":
            return "UTC"
        try:
            ZoneInfo(cleaned)
        except (ZoneInfoNotFoundError, ValueError) as error:
            raise ValueError(f"Invalid timezone: {value}") from error
        return cleaned

    @model_validator(mode="after")
    def require_a_time_when_enabled(self) -> "UpdateYoutubeLiveSyncRequest":
        if self.enabled and not self.run_times:
            raise ValueError("run_times is required when the schedule is enabled")
        return self


class RunYoutubeLiveSyncRequest(BaseModel):
    event_ids: List[UUID] = Field(min_length=1, max_length=MAX_EVENTS_PER_REQUEST)

    @field_validator("event_ids")
    @classmethod
    def validate_event_ids(cls, values: List[UUID]) -> List[UUID]:
        return _dedupe(values)


class YoutubeLiveSyncScheduleDTO(BaseModel):
    event_id: str
    enabled: bool
    run_times: List[str]
    timezone: str = Field(description="Timezone the run times are read in (the default when none was set).")
    last_run_at: Optional[datetime] = None
    last_run_added: Optional[int] = None
    last_run_error: Optional[str] = None


class YoutubeLiveSyncListDTO(BaseModel):
    group_id: str
    channel_url: Optional[str] = Field(
        default=None,
        description="The group's YouTube channel link that is checked; null when the group has none, in which case nothing runs.",
    )
    schedules: List[YoutubeLiveSyncScheduleDTO]


class YoutubeLiveSyncRunDTO(BaseModel):
    live_streams_found: int
    events_checked: int
    links_added: int
    skipped_unknown_language: int
