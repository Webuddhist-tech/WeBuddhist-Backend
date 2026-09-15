from sqlalchemy import Column, String, DateTime, UUID, Index, UniqueConstraint
from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime


class TimerAudio(Base):
    """A timer audio together with its cover image.

    Every user can upload their own, and every audio is listed to everyone, so
    a user can pick any of them for their own timer. ``user_id`` is the owner:
    it decides who may rename or delete the audio, not who may see it.

    Pairing audio with its image here is what makes "an audio always has an
    image" true by construction, rather than a rule each write has to honour.
    """

    __tablename__ = "timer_audios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    name = Column(String(255), nullable=False)
    audio_s3_key = Column(String(1000), nullable=False)
    image_s3_key = Column(String(1000), nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(_datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(_datetime.timezone.utc), onupdate=lambda: datetime.now(_datetime.timezone.utc))

    __table_args__ = (
        Index("idx_timer_audios_user_id", "user_id"),
        UniqueConstraint("user_id", "name", name="uq_timer_audios_user_name"),
    )
