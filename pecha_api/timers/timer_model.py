from sqlalchemy import Column, String, DateTime, UUID, Text, Index, Integer, Boolean, ForeignKey
from sqlalchemy.orm import relationship
from ..db.database import Base
from uuid import uuid4
import _datetime
from _datetime import datetime
from .timer_enums import TimerTypeEnum


class Timer(Base):
    __tablename__ = "timers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(UUID(as_uuid=True), nullable=False)
    group_id = Column(UUID(as_uuid=True), nullable=True)
    type = Column(TimerTypeEnum, nullable=False)
    name = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    duration = Column(Integer, nullable=False)
    # The audio and its cover image live in timer_audios, so a timer points at
    # one instead of carrying loose S3 keys. SET NULL: deleting an audio must
    # not take the timers that used it (and their history) with it.
    timer_audio_id = Column(
        UUID(as_uuid=True),
        ForeignKey("timer_audios.id", ondelete="SET NULL"),
        nullable=True,
    )
    ambient_sound_id = Column(
        UUID(as_uuid=True),
        ForeignKey("ambient_sounds.id", ondelete="SET NULL"),
        nullable=True,
    )
    bell_at_start = Column(Boolean, nullable=False, default=True)
    bell_at_end = Column(Boolean, nullable=False, default=True)
    # For a user-created timer, the preset it was customized from. Presets
    # themselves have no parent (NULL).
    parent_preset_id = Column(
        UUID(as_uuid=True),
        ForeignKey("timers.id", ondelete="SET NULL"),
        nullable=True,
    )

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(_datetime.timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(_datetime.timezone.utc), onupdate=lambda: datetime.now(_datetime.timezone.utc))
    deleted_at = Column(DateTime(timezone=True), nullable=True)

    # Eager: the DTO always needs it, and it must survive the session closing.
    timer_audio = relationship("TimerAudio", lazy="joined")

    __table_args__ = (
        Index("idx_timers_user_id", "user_id"),
        Index("idx_timers_type", "type"),
        Index("idx_timers_ambient_sound_id", "ambient_sound_id"),
        Index("idx_timers_timer_audio_id", "timer_audio_id"),
        Index("idx_timers_parent_preset_id", "parent_preset_id"),
    )
