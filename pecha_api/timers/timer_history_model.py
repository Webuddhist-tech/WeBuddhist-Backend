from sqlalchemy import Column, DateTime, UUID, Integer, ForeignKey, Index
from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime


class TimerHistory(Base):
    __tablename__ = "timer_history"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    timer_id = Column(UUID(as_uuid=True), ForeignKey("timers.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    duration_ms = Column(Integer, nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(_datetime.timezone.utc), nullable=False)

    __table_args__ = (
        Index("idx_timer_history_timer_id", "timer_id"),
        Index("idx_timer_history_user_id", "user_id"),
    )
