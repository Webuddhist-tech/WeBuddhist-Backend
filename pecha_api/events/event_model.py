from sqlalchemy import Column, String, DateTime, UUID, ForeignKey, Index, Boolean, Integer, text
from sqlalchemy.orm import relationship
from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime

CASCADE_DELETE_ORPHAN = "all, delete-orphan"


class Event(Base):
    __tablename__ = "events"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    plan_id = Column(UUID(as_uuid=True), ForeignKey("plans.id", ondelete="SET NULL"), nullable=True)
    series_id = Column(UUID(as_uuid=True), ForeignKey("series.id", ondelete="SET NULL"), nullable=True)
    accumulator_id = Column(UUID(as_uuid=True), ForeignKey("accumulators.id", ondelete="SET NULL"), nullable=True)
    group_accumulator_id = Column(
        UUID(as_uuid=True),
        ForeignKey("group_accumulators.id", ondelete="SET NULL"),
        nullable=True,
    )
    mantra_id = Column(UUID(as_uuid=True), ForeignKey("mantra.id", ondelete="SET NULL"), nullable=True)
    timer_id = Column(UUID(as_uuid=True), ForeignKey("timers.id", ondelete="SET NULL"), nullable=True)
    group_recitation_collection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("group_recitation_collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    group_id = Column(UUID(as_uuid=True), ForeignKey("author_groups.id", ondelete="RESTRICT"), nullable=False)
    location_id = Column(UUID(as_uuid=True), ForeignKey("locations.id", ondelete="RESTRICT"), nullable=True)
    start_date = Column(DateTime(timezone=True), nullable=False)
    end_date = Column(DateTime(timezone=True), nullable=False)
    timezone = Column(String(64), nullable=True)
    image_url = Column(String(1000), nullable=True)
    featured = Column(Boolean, default=False, nullable=False)
    event_format = Column(String(10), nullable=False, server_default="hybrid")
    # Per-event kill switch for the event's chat room (CMS-controlled).
    chat_enabled = Column(Boolean, default=True, nullable=False, server_default=text("true"))
    
    is_recurring = Column(Boolean, default=False, nullable=False)
    recurrence_frequency = Column(String(20), nullable=True)
    recurrence_date_system = Column(String(20), nullable=True)
    recurrence_calendar_type = Column(String(10), nullable=True)
    recurrence_month = Column(Integer, nullable=True)
    recurrence_day = Column(Integer, nullable=True)
    recurrence_day_of_week = Column(Integer, nullable=True)
    duration_days = Column(Integer, default=1, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False)
    created_by = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))

    notification_sqs_message_id = Column(String(128), nullable=True)
    notification_dispatched_at = Column(DateTime(timezone=True), nullable=True)

    metadata_entries = relationship(
        "EventMetadata",
        back_populates="event",
        cascade=CASCADE_DELETE_ORPHAN,
        passive_deletes=True,
    )

    links = relationship(
        "EventLink",
        back_populates="event",
        cascade=CASCADE_DELETE_ORPHAN,
        passive_deletes=True,
    )

    participants = relationship(
        "GroupEventParticipant",
        back_populates="event",
        cascade=CASCADE_DELETE_ORPHAN,
        passive_deletes=True,
    )

    location = relationship("Location")

    plan = relationship("Plan")
    series = relationship("Series")
    accumulator = relationship("Accumulator")
    group_accumulator = relationship("GroupAccumulator")
    mantra = relationship("Mantra")
    timer = relationship("Timer")
    group_recitation_collection = relationship("GroupRecitationCollection")

    __table_args__ = (
        Index("idx_events_group_id", "group_id"),
        Index("idx_events_location_id", "location_id"),
        Index("idx_events_start_date", "start_date"),
        Index("idx_events_end_date", "end_date"),
        Index("idx_events_series_id", "series_id"),
        Index("idx_events_group_accumulator_id", "group_accumulator_id"),
        Index("idx_events_group_recitation_collection_id", "group_recitation_collection_id"),
        Index("idx_events_featured", "featured"),
        Index(
            "idx_events_undispatched_notifications",
            "created_at",
            postgresql_where=text("notification_sqs_message_id IS NULL"),
        ),
    )
