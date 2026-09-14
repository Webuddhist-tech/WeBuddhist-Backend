from sqlalchemy import Column, String, Boolean, Integer, DateTime, UUID
from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime


class AmbientSound(Base):
    """Curated catalog of selectable ambient sounds. The app lists these and
    the user picks one per timer (stored on timers.ambient_sound_id)."""
    __tablename__ = "ambient_sounds"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    name = Column(String(255), nullable=False)
    s3_key = Column(String(1000), nullable=False)
    is_default = Column(Boolean, nullable=False, default=False)
    display_order = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(_datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(_datetime.timezone.utc), onupdate=lambda: datetime.now(_datetime.timezone.utc))
