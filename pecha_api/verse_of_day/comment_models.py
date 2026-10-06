from datetime import datetime
import datetime as dt
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pecha_api.db.database import Base

FK_VERSE_OF_DAY_ID = "verse_of_day.id"
FK_USERS_ID = "users.id"
FK_VERSE_OF_DAY_COMMENTS_ID = "verse_of_day_comments.id"


class VerseOfDayComment(Base):
    __tablename__ = "verse_of_day_comments"

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
    parent_comment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_VERSE_OF_DAY_COMMENTS_ID, ondelete="CASCADE"),
        nullable=True,
    )
    text = Column(Text, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=True,
    )

    verse = relationship("VerseOfDay")
    user = relationship("Users")
    parent_comment = relationship(
        "VerseOfDayComment",
        remote_side=[id],
        foreign_keys=[parent_comment_id],
        back_populates="replies",
    )
    replies = relationship(
        "VerseOfDayComment",
        foreign_keys=[parent_comment_id],
        back_populates="parent_comment",
    )

    __table_args__ = (
        Index("idx_verse_of_day_comments_verse_id", "verse_id"),
        Index("idx_verse_of_day_comments_user_id", "user_id"),
        Index("idx_verse_of_day_comments_parent_comment_id", "parent_comment_id"),
        Index(
            "idx_verse_of_day_comments_feed",
            "verse_id",
            "created_at",
            "id",
        ),
    )
