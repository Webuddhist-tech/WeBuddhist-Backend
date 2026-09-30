from datetime import datetime, timezone
from typing import List

from sqlalchemy import Integer, cast, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .recitation_play_time_model import RecitationSegmentPlayTime


def add_play_time_sample(db: Session, text_id: str, segment_id: str, duration_ms: int) -> None:
    """Fold one measured play time into the segment's running figures.

    A single upsert, so two instances measuring the same line at once both
    count: the new average is worked out from the stored total inside the
    statement, never from a value read beforehand.

    Does not commit; callers own the transaction boundary."""
    now = datetime.now(timezone.utc)
    table = RecitationSegmentPlayTime
    stmt = insert(table).values(
        text_id=text_id,
        segment_id=segment_id,
        sample_count=1,
        total_duration_ms=duration_ms,
        average_duration_ms=duration_ms,
        last_duration_ms=duration_ms,
        updated_at=now,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["text_id", "segment_id"],
        set_={
            "sample_count": table.sample_count + 1,
            "total_duration_ms": table.total_duration_ms + duration_ms,
            "average_duration_ms": cast(
                (table.total_duration_ms + duration_ms) / (table.sample_count + 1),
                Integer,
            ),
            "last_duration_ms": duration_ms,
            "updated_at": now,
        },
    )
    db.execute(stmt)


def get_play_times_for_text(db: Session, text_id: str) -> List[RecitationSegmentPlayTime]:
    return list(
        db.execute(
            select(RecitationSegmentPlayTime).where(RecitationSegmentPlayTime.text_id == text_id)
        ).scalars()
    )
