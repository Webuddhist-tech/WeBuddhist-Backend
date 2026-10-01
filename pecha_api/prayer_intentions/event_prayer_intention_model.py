from sqlalchemy import Column, ForeignKey, Index, UUID
from sqlalchemy.orm import relationship

from pecha_api.db.database import Base


class EventPrayerIntention(Base):
    __tablename__ = "event_prayer_intentions"

    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    intention_id = Column(
        UUID(as_uuid=True),
        ForeignKey("prayer_intentions.id", ondelete="RESTRICT"),
        primary_key=True,
        nullable=False,
    )

    event = relationship("Event", back_populates="prayer_intention_links")
    intention = relationship("PrayerIntention", back_populates="event_links")

    __table_args__ = (
        Index("idx_event_prayer_intentions_intention_id", "intention_id"),
    )
