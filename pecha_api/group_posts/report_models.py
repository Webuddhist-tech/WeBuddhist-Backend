"""Moderation reports filed against a group's posts and comments.

Deliberately a parallel table to `chat_message_reports` rather than a shared
polymorphic one: the two carry different context columns, and a group's queue
joins them at read time instead.
"""
from datetime import datetime
import datetime as dt
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from pecha_api.db.database import Base

FK_GROUP_POSTS_ID = "group_posts.id"
FK_GROUP_POST_COMMENTS_ID = "group_post_comments.id"
FK_USERS_ID = "users.id"


class GroupPostReport(Base):
    __tablename__ = "group_post_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # Always set, including for a COMMENT report: the group's queue is built
    # by joining post_id -> group_posts.group_id, so a comment report must
    # carry its post rather than only the comment.
    post_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_GROUP_POSTS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    comment_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_GROUP_POST_COMMENTS_ID, ondelete="CASCADE"),
        nullable=True,
    )
    reporter_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID, ondelete="CASCADE"),
        nullable=False,
    )
    reported_user_id = Column(
        UUID(as_uuid=True),
        ForeignKey(FK_USERS_ID, ondelete="CASCADE"),
        nullable=True,
    )
    target_type = Column(String(16), nullable=False)
    # Snapshot of the reported text, so the queue still shows what was
    # reported after the post or comment is deleted.
    content_text = Column(Text, nullable=True)
    reason = Column(String(32), nullable=False)
    description = Column(Text, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(dt.timezone.utc),
        nullable=False,
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    post = relationship("GroupPost", foreign_keys=[post_id])
    comment = relationship("GroupPostComment", foreign_keys=[comment_id])
    reporter = relationship("Users", foreign_keys=[reporter_id])
    reported_user = relationship("Users", foreign_keys=[reported_user_id])

    __table_args__ = (
        CheckConstraint(
            "(target_type = 'POST' AND comment_id IS NULL) OR "
            "(target_type = 'COMMENT' AND comment_id IS NOT NULL)",
            name="ck_group_post_reports_target_shape",
        ),
        Index("idx_group_post_reports_post_id", "post_id"),
        Index("idx_group_post_reports_comment_id", "comment_id"),
        Index("idx_group_post_reports_created_at", "created_at"),
        # One report per reporter per target. Two partial indexes rather than
        # a plain UNIQUE, because Postgres exempts NULL from a unique index -
        # (post_id, NULL, reporter_id) would never collide with itself and a
        # user could report the same post repeatedly.
        Index(
            "uq_group_post_reports_post_reporter",
            "post_id",
            "reporter_id",
            unique=True,
            postgresql_where=Column("comment_id").is_(None),
        ),
        Index(
            "uq_group_post_reports_comment_reporter",
            "comment_id",
            "reporter_id",
            unique=True,
            postgresql_where=Column("comment_id").isnot(None),
        ),
    )
