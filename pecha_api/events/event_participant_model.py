from sqlalchemy import Column, DateTime, String, UUID, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship
from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime


class GroupEventParticipant(Base):
    __tablename__ = "group_event_participants"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )

    # How the user attends: "online" | "offline". NULL means they joined
    # without picking - only possible on a hybrid event, where neither side
    # can be inferred from the event itself.
    participation_type = Column(String(10), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))

    event = relationship("Event", back_populates="participants")
    user = relationship("Users")

    __table_args__ = (
        UniqueConstraint("event_id", "user_id", name="uq_group_event_participants_event_user"),
        Index("idx_group_event_participants_event_id", "event_id"),
        Index("idx_group_event_participants_user_id", "user_id"),
    )
