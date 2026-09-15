from sqlalchemy import Column, String, DateTime, UUID, Text, Index, Integer
from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime
from .timer_enums import TimerTypeEnum


class Timer(Base):
    __tablename__ = "timers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    group_id = Column(UUID(as_uuid=True), nullable=True)
    type = Column(TimerTypeEnum, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    duration = Column(Integer, nullable=False)
    audio_url = Column(String(1000), nullable=True)
    image_url = Column(String(1000), nullable=True)
    
    created_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), onupdate=datetime.now(_datetime.timezone.utc))

    __table_args__ = (
        Index("idx_timers_user_id", "user_id"),
        Index("idx_timers_type", "type"),
    )
