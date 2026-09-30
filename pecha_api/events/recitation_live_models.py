from typing import List, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class SetPositionFrame(BaseModel):
    """An operator's `set` frame: where the puja is right now.

    `segment_id` is the wire key - stable across content edits, and resolvable
    by each client into its own language through the segment's mappings.
    `text_id` says which liturgy that segment belongs to, so a client whose
    text is no longer the one being recited knows to load the new one rather
    than silently failing to find the segment: an event's recitation collection
    holds several texts, and the operator works through them in order.
    `index` is advisory only, kept so the existing OBS overlays keep working.
    """

    # Matches group_recitation_collection_items.text_id: not UUID-only, since
    # it can hold an external (pecha-style) text id too.
    text_id: str = Field(..., max_length=255)
    segment_id: str = Field(..., max_length=128)
    index: Optional[int] = Field(None, ge=0)
    round_number: Optional[int] = Field(None, ge=1)
    # Set by the controller's autoplay. Such a move is timed by the play times
    # themselves, so it is not measured back into them.
    autoplay: bool = False
    # The controller's name for an unbroken stretch of this text: kept for as
    # long as every move the controller makes includes the text, replaced when a
    # move leaves it out. Two lines are only timed against each other within one
    # run, so time the room spent on another text is never billed to this one.
    # Without it nothing is timed.
    run: Optional[str] = Field(None, pattern=r"^[A-Za-z0-9_-]{1,64}$")

    @field_validator("text_id", "segment_id")
    @classmethod
    def validate_not_empty(cls, value: str, info) -> str:
        if not value or not value.strip():
            raise ValueError(f"{info.field_name} must not be empty")
        return value.strip()


class PositionAcceptedResponse(BaseModel):
    """What an HTTP emitter gets back: the position as the room received it."""

    event_id: UUID
    text_id: str
    segment_id: str
    index: Optional[int] = None
    round_number: Optional[int] = None
    server_time: str
    revision: Optional[int] = Field(
        None,
        description="Ordering key the position was stored under; None when the snapshot could not be written",
    )


class SegmentPlayTime(BaseModel):
    """How long one line takes to recite, as learned from past pujas."""

    segment_id: str
    average_duration_ms: int
    last_duration_ms: int
    sample_count: int


class SegmentPlayTimesResponse(BaseModel):
    text_id: str
    segments: List[SegmentPlayTime]
