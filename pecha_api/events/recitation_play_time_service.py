import logging
from typing import Optional
from uuid import UUID

from starlette.concurrency import run_in_threadpool

from pecha_api.db.database import SessionLocal
from pecha_api.events.recitation_live_models import SegmentPlayTime, SegmentPlayTimesResponse
from pecha_api.events.recitation_play_time_repository import (
    add_play_time_sample,
    get_play_times_for_text,
)
from pecha_api.events.recitation_websocket import RecitationBroadcaster

logger = logging.getLogger(__name__)

# Anything quicker is the operator skipping past a line, not reciting it.
MIN_SEGMENT_PLAY_MS = 300
# Anything slower is a pause - a talk, a break, an operator who stepped away -
# and would teach the controller to wait for minutes on an ordinary line.
MAX_SEGMENT_PLAY_MS = 3 * 60 * 1000


def _line(index: Optional[int], round_number: Optional[int], segment_id: str) -> str:
    """Names a line: the same segment in another round is recited again, so it
    is a different line."""
    return f"{'' if index is None else index}|{'' if round_number is None else round_number}|{segment_id}"


def _parse_mark(mark: str) -> Optional[tuple]:
    """`<revision>|<accepted at ms>|<index>|<round>|<segment id>` back into
    (accepted at ms, index, segment id); None for anything unreadable."""
    parts = mark.split("|", 4)
    if len(parts) != 5:
        return None
    _, accepted_at, index, _, segment_id = parts
    try:
        return int(accepted_at), (int(index) if index else None), segment_id
    except ValueError:
        return None


def _save_sample(text_id: str, segment_id: str, duration_ms: int) -> None:
    with SessionLocal() as db:
        add_play_time_sample(db, text_id=text_id, segment_id=segment_id, duration_ms=duration_ms)
        db.commit()


async def record_segment_play_time(
    broadcaster: RecitationBroadcaster,
    event_id: UUID,
    text_id: str,
    segment_id: str,
    index: Optional[int],
    round_number: Optional[int],
    revision: Optional[int],
    accepted_at_ms: int,
    autoplay: bool = False,
) -> None:
    """Measure the line the room just left, now that it has moved on.

    Runs after the position has gone out to the room, never in front of it, and
    swallows every failure: a lost sample costs nothing, a delayed position
    costs the whole room its place.

    Only a step to the very next line is a measurement. A jump - back to repeat
    a passage, forward past a skipped section - says nothing about how long the
    line left behind takes to recite. Neither is a move the controller's
    autoplay made: its timing came from these figures, and feeding it back would
    only drown out the operator's real ones. It still marks where the room is,
    so the operator's next move is measured from the right line.

    A move onto another text, and the gap between two sessions, are ruled out by
    the mark store itself: it keeps only the text the room is on, and marks from
    a session that has ended are never handed back. Both have to be settled
    there, because this runs as unordered background work and cannot tell how
    much happened between two marks.
    """
    try:
        if revision is None:
            # Without a revision the mark cannot be ordered against the others.
            return
        line = _line(index, round_number, segment_id)
        previous = await broadcaster.swap_segment_mark(
            event_id=event_id,
            text_id=text_id,
            mark=f"{revision}|{accepted_at_ms}|{line}",
            revision=revision,
            line=line,
        )
        if previous is None or autoplay:
            return
        parsed = _parse_mark(previous)
        if parsed is None:
            return
        started_at_ms, previous_index, previous_segment_id = parsed
        if index is None or previous_index is None or index != previous_index + 1:
            return
        duration_ms = accepted_at_ms - started_at_ms
        if not MIN_SEGMENT_PLAY_MS <= duration_ms <= MAX_SEGMENT_PLAY_MS:
            return
        # Synchronous SQLAlchemy, kept off the event loop every socket shares.
        await run_in_threadpool(_save_sample, text_id, previous_segment_id, duration_ms)
    except Exception as e:
        logger.exception("Failed to record recitation segment play time: %s", e)


def get_segment_play_times(text_id: str) -> SegmentPlayTimesResponse:
    with SessionLocal() as db:
        rows = get_play_times_for_text(db, text_id=text_id)
        return SegmentPlayTimesResponse(
            text_id=text_id,
            segments=[
                SegmentPlayTime(
                    segment_id=row.segment_id,
                    average_duration_ms=row.average_duration_ms,
                    last_duration_ms=row.last_duration_ms,
                    sample_count=row.sample_count,
                )
                for row in rows
            ],
        )
