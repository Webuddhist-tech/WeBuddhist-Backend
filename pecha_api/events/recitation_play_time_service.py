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
    """`<revision>|<accepted at ms>|<autoplay 0/1>|<run>|<index>|<round>|<segment id>`
    back into (accepted at ms, autoplay, run, index, segment id); None for
    anything unreadable."""
    parts = mark.split("|", 6)
    if len(parts) != 7:
        return None
    _, accepted_at, autoplay, run, index, _, segment_id = parts
    try:
        return (
            int(accepted_at),
            autoplay == "1",
            run,
            (int(index) if index else None),
            segment_id,
        )
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
    run: Optional[str] = None,
) -> None:
    """Measure the line the room just left, now that it has moved on.

    Runs after the position has gone out to the room, never in front of it, and
    swallows every failure: a lost sample costs nothing, a delayed position
    costs the whole room its place.

    Only a step to the very next line is a measurement. A jump - back to repeat
    a passage, forward past a skipped section - says nothing about how long the
    line left behind takes to recite. Nor is a line autoplay had any hand in -
    moved onto by it, or moved off by it: its timing came from these figures,
    and feeding it back would only drown out the operator's real ones. Such a
    move still marks where the room is, flagged, so the next move knows.

    Nor is a step that spans time the room spent on another text. The
    controller names each unbroken stretch of a text with a run, replaced
    whenever one of its moves leaves the text out, so two marks of the same run
    had the text in every move between them. A position without a run cannot
    say so and is never measured. The gap between two sessions is ruled out by
    the mark store, which hands back nothing from a session that has ended.
    """
    try:
        if revision is None:
            # Without a revision the mark cannot be ordered against the others.
            return
        line = _line(index, round_number, segment_id)
        previous = await broadcaster.swap_segment_mark(
            event_id=event_id,
            text_id=text_id,
            mark=f"{revision}|{accepted_at_ms}|{1 if autoplay else 0}|{run or ''}|{line}",
            revision=revision,
            line=line,
        )
        if previous is None or autoplay:
            return
        parsed = _parse_mark(previous)
        if parsed is None:
            return
        started_at_ms, started_by_autoplay, previous_run, previous_index, previous_segment_id = parsed
        if started_by_autoplay:
            return
        if not run or previous_run != run:
            return
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
