from sqlalchemy import Column, String, DateTime, UUID, Index, UniqueConstraint
from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime
from .timer_audio_enums import TimerAudioTypeEnum


class TimerAudio(Base):
    """A named timer audio, with an optional cover image.

    Two kinds, distinguished by ``type``:

    * PRESET - curated in Studio, has no owner (``user_id`` is NULL) and is
      listed to everybody.
    * USER - uploaded by one person, listed only back to them.

    Visibility follows from those two rules, so it is decided in one place
    (``list_visible_timer_audios``) rather than at each call site.
    """

    __tablename__ = "timer_audios"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    # NULL for presets: they belong to the catalogue, not to a person.
    user_id = Column(UUID(as_uuid=True), nullable=True)
    type = Column(TimerAudioTypeEnum, nullable=False)
    name = Column(String(255), nullable=False)
    audio_s3_key = Column(String(1000), nullable=False)
    image_s3_key = Column(String(1000), nullable=True)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(_datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(_datetime.timezone.utc), onupdate=lambda: datetime.now(_datetime.timezone.utc))

    __table_args__ = (
        Index("idx_timer_audios_user_id", "user_id"),
        Index("idx_timer_audios_type", "type"),
        # Scoped to the owner, so two people may both name one "Bell".
        # Presets share a NULL user_id, and Postgres treats NULLs as distinct,
        # so this does not constrain preset names.
        UniqueConstraint("user_id", "name", name="uq_timer_audios_user_name"),
    )
