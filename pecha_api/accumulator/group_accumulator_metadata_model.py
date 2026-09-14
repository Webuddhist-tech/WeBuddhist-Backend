from uuid import uuid4

from sqlalchemy import Column, Text, UUID, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship

from ..db.database import Base
from ..plans.plans_enums import LanguageCodeEnum


class GroupAccumulatorMetadata(Base):
    """Unlike AccumulatorMetadata there is no name — the group accumulator
    carries its own title."""
    __tablename__ = "group_accumulator_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_accumulator_id = Column(
        UUID(as_uuid=True),
        ForeignKey("group_accumulators.id", ondelete="CASCADE"),
        nullable=False,
    )
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
