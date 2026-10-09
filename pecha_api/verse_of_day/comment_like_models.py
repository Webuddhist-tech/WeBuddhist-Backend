from datetime import datetime
import datetime as dt
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pecha_api.db.database import Base

FK_VERSE_OF_DAY_COMMENTS_ID = "verse_of_day_comments.id"
FK_USERS_ID = "users.id"


class VerseOfDayCommentLike(Base):
    __tablename__ = "verse_of_day_comment_likes"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    comment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_VERSE_OF_DAY_COMMENTS_ID, ondelete="CASCADE"),
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

    comment = relationship("VerseOfDayComment")
    user = relationship("Users")

    __table_args__ = (
        UniqueConstraint(
            "comment_id",
            "user_id",
            name="uq_verse_of_day_comment_likes_comment_user",
        ),
        Index("idx_verse_of_day_comment_likes_comment_id", "comment_id"),
        Index("idx_verse_of_day_comment_likes_user_id", "user_id"),
        Index(
            "idx_verse_of_day_comment_likes_comment_created",
            "comment_id",
            "created_at",
            "id",
        ),
    )
