from datetime import datetime
import datetime as dt
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pecha_api.db.database import Base

FK_VERSE_OF_DAY_ID = "verse_of_day.id"
FK_USERS_ID = "users.id"


class VerseOfDayLike(Base):
    __tablename__ = "verse_of_day_likes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    verse_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_VERSE_OF_DAY_ID, ondelete="CASCADE"),
        nullable=False,
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )

    verse = relationship("VerseOfDay")
    user = relationship("Users")

    __table_args__ = (
        UniqueConstraint("verse_id", "user_id", name="uq_verse_of_day_likes_verse_user"),
        Index("idx_verse_of_day_likes_verse_id", "verse_id"),
        Index("idx_verse_of_day_likes_user_id", "user_id"),
    )
