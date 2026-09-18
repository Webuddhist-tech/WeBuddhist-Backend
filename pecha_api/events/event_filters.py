from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from .event_response_models import EventFormat


@dataclass(frozen=True)
class EventContentFilter:
    """Which content association(s) events must be linked to, for querying."""
    group_id: Optional[UUID] = None
    plan_id: Optional[UUID] = None
    accumulator_id: Optional[UUID] = None
    mantra_id: Optional[UUID] = None
    timer_id: Optional[UUID] = None
    group_recitation_collection_id: Optional[UUID] = None
    event_format: Optional[EventFormat] = None
