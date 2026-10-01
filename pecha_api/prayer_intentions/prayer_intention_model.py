from sqlalchemy import Column, String, Integer, Text, DateTime, UUID
from sqlalchemy.orm import relationship
from uuid import uuid4
import _datetime
from _datetime import datetime

from pecha_api.db.database import Base


class PrayerIntention(Base):
    """Catalog of prayer-request intention types (slug, color, copy)."""

    __tablename__ = "prayer_intentions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    slug = Column(String(32), nullable=False, unique=True)
    label = Column(String(64), nullable=False)
    color = Column(String(16), nullable=False)
    description = Column(Text, nullable=False)
    display_order = Column(Integer, nullable=False, default=0)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(_datetime.timezone.utc),
        nullable=False,
    )

    event_links = relationship(
        "EventPrayerIntention",
        back_populates="intention",
        passive_deletes=True,
    )
