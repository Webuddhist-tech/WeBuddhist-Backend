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
    # How long the controller held the line this move leaves behind, measured on
    # its own monotonic clock. The controller is the only place that knows when
    # the operator actually left the line: a duration worked out here instead
    # would be the gap between two HTTP arrivals, and would carry the network,
    # the liveness check, the throttle and the controller's own send pacing into
    # a figure that is meant to be speech alone. Advisory: whether this move is
    # measured at all is still settled here, and the duration is clamped.
    elapsed_ms: Optional[int] = Field(None, ge=0)
    # The line (by index in this text) this move follows on from in recitation
    # order, when that is not simply the line before it: Next stepping over
    # yigchung, which is never recited, or a Return taken from the end of a
    # passage back to its start. Either way the line left behind was recited
    # through, so it may be timed - but only if the room's last line for this
    # text is that very line, so a move whose predecessor never arrived is still
    # not timed.
    from_index: Optional[int] = Field(None, ge=0)

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


# A move is one line in every edition being followed: a handful, never dozens.
MAX_POSITIONS_PER_MOVE = 20


class PublishMoveRequest(BaseModel):
    """One move: the same line in every edition the room follows.

    Sent as one request rather than one per edition, so the edition on screen
    is not held back a whole round trip behind the others. The positions go
    out to the room in the order given, and the event keeps the last one, so
    the controller puts the edition it is reading last.
    """

    positions: List[SetPositionFrame] = Field(
        ..., min_length=1, max_length=MAX_POSITIONS_PER_MOVE
    )


class MoveAcceptedResponse(BaseModel):
    """Each position of a move as the room received it, in the order sent."""

    positions: List[PositionAcceptedResponse]


# Autoplay runs a whole puja from one plan, repeated passages laid out in full.
MAX_AUTOPLAY_STEPS = 5000
# Anything shorter is not a line recited; it would race the room through the
# plan. Matches the shortest play time the recorder keeps.
MIN_AUTOPLAY_STEP_MS = 300
# Anything longer is a pause, not a line - again the recorder's own ceiling.
MAX_AUTOPLAY_STEP_MS = 3 * 60 * 1000


class AutoplayStep(BaseModel):
    """One line of the plan: every edition's position for it, and how long the
    room is held on it before the next step."""

    positions: List[SetPositionFrame] = Field(
        ..., min_length=1, max_length=MAX_POSITIONS_PER_MOVE
    )
    duration_ms: int = Field(..., ge=MIN_AUTOPLAY_STEP_MS, le=MAX_AUTOPLAY_STEP_MS)


class AutoplayStartRequest(BaseModel):
    """Start autoplay, or replace the plan it is running.

    The controller lays the plan out itself - which lines, which rounds, where
    the Returns go - so the backend never needs to know what a Return is: it
    holds each step for its time and moves on. The first step goes out at once.
    """

    steps: List[AutoplayStep] = Field(..., min_length=1, max_length=MAX_AUTOPLAY_STEPS)
    # Set when the first step is the line the room is already on and has been
    # for this long - a plan changed mid-line, say a round count altered. It is
    # then not sent again, only held for whatever is left of its time.
    first_step_elapsed_ms: Optional[int] = Field(None, ge=0, le=MAX_AUTOPLAY_STEP_MS)


class AutoplayStateResponse(BaseModel):
    """Where autoplay is: sent back by every command, and pushed to the
    operator's socket as a `type: "autoplay"` frame whenever it changes."""

    type: str = "autoplay"
    event_id: UUID
    plan_id: Optional[str] = None
    status: str = Field(..., description="running | stopped")
    reason: Optional[str] = Field(
        None, description="Why it stopped: finished | stopped | ended | failed"
    )
    step: int = 0
    total_steps: int = 0
    step_started_at_ms: Optional[int] = Field(
        None, description="When the current step went out, epoch ms on the server"
    )
    step_duration_ms: Optional[int] = None
    server_time_ms: int = Field(
        ..., description="The server's clock when this was sent, to line the two clocks up"
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
