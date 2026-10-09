from uuid import uuid4

from sqlalchemy import Column, String, UUID, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import relationship

from pecha_api.db.database import Base
from pecha_api.plans.plans_enums import LanguageCodeEnum


class LocationMetadata(Base):
    """A location's name in one language.

    `locations.name` stays the canonical name and is what a reader gets when
    the language they asked for has no row here (see the English fallback in
    event_service._location_to_dto).
    """

    __tablename__ = "location_metadata"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    location_id = Column(
        UUID(as_uuid=True),
        ForeignKey("locations.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(255), nullable=False)
    language = Column(LanguageCodeEnum, nullable=False)

    location = relationship("Location", back_populates="metadata_entries")

    __table_args__ = (
        UniqueConstraint(
            "location_id", "language", name="uq_location_metadata_location_language"
        ),
        Index("idx_location_metadata_location_language", "location_id", "language"),
    )
