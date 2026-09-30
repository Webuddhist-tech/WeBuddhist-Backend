from sqlalchemy import BigInteger, Column, DateTime, Integer, String, text

from ..db.database import Base


class RecitationSegmentPlayTime(Base):
    """How long one line of a liturgy takes to recite, learned from live pujas.

    One row per segment of a text, not per event: the same liturgy recited at
    another event is the same lines, so every session sharpens one figure. The
    live controller reads these back to advance the room on its own.

    Each sample is the time from the operator landing on this line to landing on
    the next one. The average is kept alongside its inputs so it can be served as
    is and still be recomputed exactly as new samples come in.
    """

    __tablename__ = "recitation_segment_play_times"

    # Matches group_recitation_collection_items.text_id: not UUID-only, since
    # it can hold an external (pecha-style) text id too.
    text_id = Column(String(255), primary_key=True)
    segment_id = Column(String(128), primary_key=True)
    sample_count = Column(Integer, nullable=False, server_default=text("0"))
    total_duration_ms = Column(BigInteger, nullable=False, server_default=text("0"))
    average_duration_ms = Column(Integer, nullable=False)
    last_duration_ms = Column(Integer, nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
