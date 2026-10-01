from sqlalchemy import Column, DateTime, UUID, Integer, String, Text, ForeignKey, Index
from sqlalchemy.orm import relationship
from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime

from .accumulator_enums import GroupAccumulatorLinkTypeEnum


class GroupAccumulatorLink(Base):
    """`link_type` and `video_id` are derived from the URL at save time, not
    sent by the client."""
    __tablename__ = "group_accumulator_links"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_accumulator_id = Column(
        UUID(as_uuid=True),
        ForeignKey("group_accumulators.id", ondelete="CASCADE"),
        nullable=False,
    )
    url = Column(Text, nullable=False)
    link_type = Column(GroupAccumulatorLinkTypeEnum, nullable=False)
    video_id = Column(String(64), nullable=True)
    title = Column(String(500), nullable=True)
    display_order = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(_datetime.timezone.utc), nullable=False)
    created_by = Column(String(255), nullable=True)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(_datetime.timezone.utc), onupdate=lambda: datetime.now(_datetime.timezone.utc))
    updated_by = Column(String(255), nullable=True)

    group_accumulator = relationship("GroupAccumulator", back_populates="links")

    __table_args__ = (
        Index("idx_group_accumulator_links_group_accumulator_id", "group_accumulator_id"),
    )
