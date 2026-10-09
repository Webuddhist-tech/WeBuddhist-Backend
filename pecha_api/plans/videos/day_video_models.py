from sqlalchemy import Column, Integer, DateTime, ForeignKey, Index, UUID, String, Text
from sqlalchemy.orm import relationship
from uuid import uuid4
from pecha_api.db.database import Base
from _datetime import datetime
import _datetime


class DayVideo(Base):
    __tablename__ = "day_videos"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    day_id = Column(
        UUID(as_uuid=True),
        ForeignKey("items.id", ondelete="CASCADE"),
        nullable=False,
    )
    url = Column(Text, nullable=False)
    video_id = Column(String(64), nullable=True)
    title = Column(String(500), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    display_order = Column(Integer, nullable=False, default=0)

    created_at = Column(
        DateTime(timezone=True),
        default=datetime.now(_datetime.timezone.utc),
        nullable=False,
    )
    created_by = Column(String(255), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now(_datetime.timezone.utc),
    )
    updated_by = Column(String(255))

    plan_item = relationship("PlanItem", back_populates="videos")

    __table_args__ = (
        Index("idx_day_videos_day_id", "day_id"),
    )
