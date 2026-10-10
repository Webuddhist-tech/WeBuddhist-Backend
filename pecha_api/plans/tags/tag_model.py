from sqlalchemy import Boolean, Column, Integer, String, DateTime, UUID, ForeignKey, Table, Index, text
from sqlalchemy.orm import relationship
from uuid import uuid4
import _datetime
from _datetime import datetime

from pecha_api.db.database import Base
from pecha_api.plans.plans_enums import LanguageCodeEnum

plan_tags = Table(
    "plan_tags",
    Base.metadata,
    Column("plan_id", UUID(as_uuid=True), ForeignKey("plans.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

tag_segments = Table(
    "tag_segments",
    Base.metadata,
    Column("tag_id", UUID(as_uuid=True), ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    Column("segment_id", String(255), primary_key=True),
    Column("language", LanguageCodeEnum, primary_key=True, nullable=False),
)


class Tag(Base):
    __tablename__ = "tags"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    image_key = Column(String(1000), nullable=True)
    featured = Column(Boolean, default=False, nullable=False)
    display_order = Column(Integer, nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc))
    updated_by = Column(String(255))
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(String(255))

    plans = relationship("Plan", secondary=plan_tags, back_populates="tag_list")
    metadata_entries = relationship("TagMetadata", back_populates="tag", cascade="all, delete-orphan")

    __table_args__ = (
        Index(
            "idx_tags_featured",
            "featured",
            postgresql_where=text("featured = TRUE AND deleted_at IS NULL"),
        ),
    )
