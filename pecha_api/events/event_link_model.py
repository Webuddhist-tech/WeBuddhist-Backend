from uuid import uuid4
import _datetime
from _datetime import datetime

from sqlalchemy import Column, String, Integer, DateTime, UUID, ForeignKey, Index
from sqlalchemy.orm import relationship

from ..db.database import Base
from pecha_api.plans.plans_enums import LanguageCodeEnum


class EventLink(Base):
    __tablename__ = "event_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    type = Column(String(50), nullable=False)
    url = Column(String(2000), nullable=False)
    label = Column(String(255), nullable=True)
    language = Column(LanguageCodeEnum, nullable=False)
    display_order = Column(Integer, nullable=False, default=1)

    created_at = Column(
        DateTime(timezone=True),
        default=datetime.now(_datetime.timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now(_datetime.timezone.utc),
    )

    event = relationship("Event", back_populates="links")

    __table_args__ = (
        Index("idx_event_links_event_id", "event_id"),
        Index("idx_event_links_event_language", "event_id", "language"),
    )
