from uuid import uuid4

from sqlalchemy import Column, String, Text, UUID, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from ..db.database import Base
from ..plans.plans_enums import LanguageCodeEnum


class GroupAccumulatorMetadata(Base):
    """Per-language title/description for a group accumulator.

    ``group_accumulators.title`` stays populated with the default (EN, else the
    first translated) title so list views, search and the other modules that
    read that column keep working."""
    __tablename__ = "group_accumulator_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_accumulator_id = Column(
        UUID(as_uuid=True),
        ForeignKey("group_accumulators.id", ondelete="CASCADE"),
        nullable=False,
    )
    title = Column(String, nullable=True)
    description = Column(Text, nullable=True)
    language = Column(LanguageCodeEnum, nullable=False)

    group_accumulator = relationship("GroupAccumulator", back_populates="metadata_entries")

    __table_args__ = (
        UniqueConstraint(
            "group_accumulator_id",
            "language",
            name="uq_group_accumulator_metadata_language",
        ),
    )
