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


def _segment_left_behind(
    previous: str,
    run: Optional[str],
    index: Optional[int],
    from_index: Optional[int],
) -> Optional[str]:
    """The segment id of the line the room just left, when the previous mark and
    this move may be timed against each other; None otherwise."""
    parsed = _parse_mark(previous)
    if parsed is None:
        return None
    _, started_by_autoplay, previous_run, previous_index, previous_segment_id = parsed
    if started_by_autoplay or not run or previous_run != run:
        return None
    if previous_index is None or index is None:
        return None
    steps_on = index == previous_index + 1
    # Taken on the controller's word only when the room's last line for this
    # text is the one it says it left, and it names the line it went to.
    follows_on = from_index is not None and from_index == previous_index
    if not (steps_on or follows_on):
        return None
    return previous_segment_id


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
    elapsed_ms: Optional[int] = None,
    from_index: Optional[int] = None,
) -> None:
    """Measure the line the room just left, now that it has moved on.

    Runs after the position has gone out to the room, never in front of it, and
    swallows every failure: a lost sample costs nothing, a delayed position
    costs the whole room its place.

    Only a step on from the line the room was on is a measurement: to the very
    next line, or - when the controller says the move follows on from that line
    with `from_index` - over yigchung, which is never recited, or back to a
    passage's start by its Return. Any other jump - back to look at a line,
    forward past a skipped section - says nothing about how long the line left
    behind takes to recite. Nor is a line autoplay had any hand in -
    moved onto by it, or moved off by it: its timing came from these figures,
    and feeding it back would only drown out the operator's real ones. Such a
    move still marks where the room is, flagged, so the next move knows.

    Nor is a step that spans time the room spent on another text. The
    controller names each unbroken stretch of a text with a run, replaced
    whenever one of its moves leaves the text out, so two marks of the same run
    had the text in every move between them. A position without a run cannot
    say so and is never measured. The gap between two sessions is ruled out by
    the mark store, which hands back nothing from a session that has ended.

    `elapsed_ms` is how long the controller held the line being left, by its own
    clock, and it is the only figure ever recorded. Whether a line's play time
    is stored or updated is the controller's call: a move without it is still
    marked, so the next move knows where the room was, but nothing is saved -
    the stored time stays as it was. The two marks are never subtracted for a
    figure here: that would measure the gap between two HTTP arrivals - the
    network, this endpoint's liveness check and throttle, the controller's send
    pacing - not the room reciting, and would overwrite a time the controller
    chose not to touch.

    What is measured is settled here either way. The controller only says how
    long; the marks say whether these two lines may be timed against each other
    at all, which is also what rules out a move whose predecessor never arrived:
    its elapsed would span a line the store never saw, and the adjacency test
    rejects it.
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
            run=run,
        )
        if previous is None or autoplay or elapsed_ms is None:
            return
        previous_segment_id = _segment_left_behind(previous, run, index, from_index)
        if previous_segment_id is None:
            return
        # Clamped whichever it came from: the controller is authorised by a
        # shared secret, so its figure is taken as a claim, not a fact.
        if not MIN_SEGMENT_PLAY_MS <= elapsed_ms <= MAX_SEGMENT_PLAY_MS:
            return
        # Synchronous SQLAlchemy, kept off the event loop every socket shares.
        await run_in_threadpool(_save_sample, text_id, previous_segment_id, elapsed_ms)
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
