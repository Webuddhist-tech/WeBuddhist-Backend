from uuid import uuid4
import _datetime
from _datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, UUID, UniqueConstraint
from sqlalchemy.orm import relationship

from ..db.database import Base


class GroupEventAccumulation(Base):
    __tablename__ = "group_event_accumulations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    group_accumulator_id = Column(
        UUID(as_uuid=True),
        ForeignKey("group_accumulators.id", ondelete="RESTRICT"),
        nullable=False,
    )
    parent_id = Column(
        UUID(as_uuid=True),
        ForeignKey("group_event_accumulations.id", ondelete="SET NULL"),
        nullable=True,
    )
    event_format = Column(String(10), nullable=False, server_default="hybrid")
    display_order = Column(Integer, nullable=False, default=1)
    count_mode = Column(String(32), nullable=False, server_default="manual_in_person")

    created_at = Column(
        DateTime(timezone=True),
        default=datetime.now(_datetime.timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.now(_datetime.timezone.utc),
        onupdate=datetime.now(_datetime.timezone.utc),
    )

    event = relationship("Event", back_populates="accumulation_links")
    group_accumulator = relationship("GroupAccumulator")
    parent = relationship(
        "GroupEventAccumulation",
        remote_side="GroupEventAccumulation.id",
        back_populates="children",
    )
    children = relationship("GroupEventAccumulation", back_populates="parent")

    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "group_accumulator_id",
            name="uq_group_event_accumulations_event_accumulator",
        ),
        Index("idx_group_event_accumulations_event_id", "event_id"),
        Index("idx_group_event_accumulations_group_accumulator_id", "group_accumulator_id"),
        Index("idx_group_event_accumulations_parent_id", "parent_id"),
    )
