from uuid import uuid4
import _datetime
from _datetime import datetime

from sqlalchemy import JSON, UUID, Boolean, Column, DateTime, ForeignKey, Index, Integer, String, text

from ..db.database import Base


class EventYoutubeLiveSync(Base):
    """A schedule an admin set up in Studio for one event: at these times of
    day, look at the group's YouTube channel and add the stream that is live
    to this event. Only events with a row here are ever touched."""

    __tablename__ = "event_youtube_live_sync"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    # The event's group, kept here so one channel lookup can serve every
    # scheduled event of a group that is due at the same moment.
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey("author_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    enabled = Column(Boolean, nullable=False, default=True, server_default=text("true"))
    # Times of day as "HH:MM" strings, read in `timezone`.
    run_times = Column(JSON, nullable=False, default=list)
    timezone = Column(String(64), nullable=True)

    # The scheduled moment (UTC) most recently claimed for a run. Compared and
    # advanced in one UPDATE so that several app instances never run the same
    # time twice.
    last_slot_at = Column(DateTime(timezone=True), nullable=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    last_run_error = Column(String(500), nullable=True)
    last_run_added = Column(Integer, nullable=True)

    created_at = Column(
        DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False
    )
    created_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))
    updated_by = Column(String(255), nullable=True)

    __table_args__ = (Index("idx_event_youtube_live_sync_group_id", "group_id"),)
