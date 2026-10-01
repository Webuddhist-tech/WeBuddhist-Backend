from sqlalchemy import Column, String, DateTime, UUID, Date, Index
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime


class VerseOfDay(Base):
    __tablename__ = "verse_of_day"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    verse_id = Column(String(255), nullable=True)
    ref_id = Column(String(255), nullable=True)
    source = Column(String(255), nullable=True)
    ref_type = Column(String(50), nullable=True)
    image_urls = Column(JSONB, nullable=True)
    group_id = Column(UUID(as_uuid=True), nullable=True)
    date = Column(Date, nullable=False)

    created_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False)
    created_by = Column(String(255), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))
    updated_by = Column(String(255))

    verse_metadata = relationship("VerseMetadata", back_populates="verse_of_day", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_verse_of_day_date", "date", unique=True),
        Index("idx_verse_of_day_ref_type", "ref_type"),
        Index("idx_verse_of_day_group_id", "group_id"),
    )
