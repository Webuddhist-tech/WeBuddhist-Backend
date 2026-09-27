from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UUID,
)
from sqlalchemy.orm import relationship

from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime


class Location(Base):
    __tablename__ = "locations"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id = Column(UUID(as_uuid=True), ForeignKey("author_groups.id", ondelete="RESTRICT"), nullable=False)
    name = Column(String(255), nullable=False)
    latitude = Column(Numeric(precision=9, scale=6), nullable=True)
    longitude = Column(Numeric(precision=9, scale=6), nullable=True)

    created_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc), nullable=False)
    created_by = Column(String(255), nullable=False)

    # Per-language names; `name` above is the canonical one and the fallback.
    metadata_entries = relationship(
        "LocationMetadata",
        back_populates="location",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        CheckConstraint(
            "latitude IS NULL OR (latitude >= -90 AND latitude <= 90)",
            name="ck_locations_latitude_range",
        ),
        CheckConstraint(
            "longitude IS NULL OR (longitude >= -180 AND longitude <= 180)",
            name="ck_locations_longitude_range",
        ),
        CheckConstraint(
            "(latitude IS NULL AND longitude IS NULL) "
            "OR (latitude IS NOT NULL AND longitude IS NOT NULL)",
            name="ck_locations_coordinates_paired",
        ),
        Index("idx_locations_group_id", "group_id"),
        Index("idx_locations_group_id_name", "group_id", "name"),
    )
