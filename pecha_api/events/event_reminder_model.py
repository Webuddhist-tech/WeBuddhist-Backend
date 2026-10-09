from sqlalchemy import (
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UUID,
    text,
)
from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime


class EventReminder(Base):
    __tablename__ = "event_reminders"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    reminder_type = Column(String(20), nullable=False)
    fire_at = Column(DateTime(timezone=True), nullable=False)
    # Local calendar date of the occurrence's *start*, never of fire_at:
    # a T_MINUS_10 whose lead time crosses midnight fires on the previous
    # day but still belongs to its own occurrence.
    occurrence_date = Column(Date, nullable=False)
    # Null on a single-day occurrence; set to 1-based position and run
    # length when the occurrence spans several days, so the reminder copy
    # can say "Day 2 of 5" without re-expanding occurrences on the send
    # path (which, for a lunar recurrence, means calendar file reads).
    day_index = Column(SmallInteger, nullable=True)
    day_total = Column(SmallInteger, nullable=True)
    sqs_message_id = Column(String(128), nullable=True)
    dispatched_at = Column(DateTime(timezone=True), nullable=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False)

    __table_args__ = (
        # The per-day key below replaces uq_event_reminders_event_type - one
        # row per (event, type) - which evt3b4c5d6e7f drops in the same
        # migration that adds occurrence_date. A schema built from this
        # metadata therefore matches a migrated database, and neither can
        # hold a reminder's identity without its occurrence date.
        Index(
            "uq_event_reminders_event_type_day",
            "event_id",
            "reminder_type",
            "occurrence_date",
            unique=True,
        ),
        Index("idx_event_reminders_event_id", "event_id"),
        Index(
            "idx_event_reminders_due",
            "fire_at",
            postgresql_where=text("dispatched_at IS NULL AND canceled_at IS NULL"),
        ),
        # idx_event_reminders_due is partial, so the retention purge -
        # which sweeps by fire_at alone - needs an unfiltered index.
        Index("idx_event_reminders_fire_at", "fire_at"),
    )
