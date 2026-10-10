from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import relationship

from pecha_api.db.database import Base
from pecha_api.text_requests.text_request_enums import TextRequestStatus


class TextRequest(Base):
    """A Studio author asking for texts (chants) the library does not have yet.

    The requester and the admin who answers are both Studio authors. `text_id`
    is the edition the admin linked once the text was added, empty until then.
    """

    __tablename__ = "text_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # SET NULL rather than CASCADE: a request outlives the account that filed
    # or answered it, so the history of what was asked and done stays.
    requester_author_id = Column(
        UUID(as_uuid=True),
        ForeignKey("authors.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Where the request was made from, when it was made inside a space.
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey("author_groups.id", ondelete="SET NULL"),
        nullable=True,
    )
    collection_id = Column(
        UUID(as_uuid=True),
        ForeignKey("group_recitation_collections.id", ondelete="SET NULL"),
        nullable=True,
    )
    message = Column(Text, nullable=False)
    # [{key, filename, content_type, size}]. S3 keys, not URLs: a URL is
    # signed per read, so storing one would store something that expires.
    attachments = Column(JSONB, nullable=False, default=list)
    status = Column(String(32), nullable=False, default=TextRequestStatus.PENDING.value)
    reply = Column(Text, nullable=True)
    text_id = Column(String(255), nullable=True)
    responder_author_id = Column(
        UUID(as_uuid=True),
        ForeignKey("authors.id", ondelete="SET NULL"),
        nullable=True,
    )
    responded_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    requester = relationship("Author", foreign_keys=[requester_author_id], lazy="joined")
    responder = relationship("Author", foreign_keys=[responder_author_id], lazy="joined")
    group = relationship("AuthorGroup", foreign_keys=[group_id])
    collection = relationship("GroupRecitationCollection", foreign_keys=[collection_id])

    __table_args__ = (
        Index("idx_text_requests_status_created_at", "status", "created_at"),
        Index("idx_text_requests_requester", "requester_author_id", "created_at"),
    )
