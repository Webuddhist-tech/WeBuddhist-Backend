from sqlalchemy import (
    Column,
    String,
    DateTime,
    Time,
    Boolean,
    Integer,
    UUID,
    Index,
    ForeignKey,
    text,
)
from sqlalchemy.orm import relationship
from uuid import uuid4
import _datetime
from _datetime import datetime

from ..db.database import Base
from .routines_enums import SessionTypeEnum


class Routine(Base):
    __tablename__ = "routines"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    timezone = Column(String(64), nullable=True)

    created_at = Column(
        DateTime(timezone=True),
        default=datetime.now(_datetime.timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc)
    )
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(String(255))

    time_blocks = relationship(
        "RoutineTimeBlock", backref="routine", passive_deletes=True
    )

    __table_args__ = (Index("idx_routines_user", "user_id"),)


class RoutineTimeBlock(Base):
    __tablename__ = "routine_time_blocks"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    routine_id = Column(
        UUID(as_uuid=True),
        ForeignKey("routines.id", ondelete="CASCADE"),
        nullable=False,
    )
    time = Column(String(5), nullable=False)
    title = Column(String(255), nullable=True)
    time_utc = Column(Time(timezone=True), nullable=False)
    time_int = Column(Integer, nullable=False)
    notification_enabled = Column(Boolean, default=True)

    created_at = Column(
        DateTime(timezone=True),
        default=datetime.now(_datetime.timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc)
    )
    deleted_at = Column(DateTime(timezone=True))
    deleted_by = Column(String(255))

    sessions = relationship(
        "RoutineSession", backref="time_block", passive_deletes=True
    )

    __table_args__ = (
        Index("idx_time_blocks_routine", "routine_id"),
        Index(
            "uq_routine_time",
            "routine_id",
            "time",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class RoutineSession(Base):
    __tablename__ = "routine_sessions"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    time_block_id = Column(
        UUID(as_uuid=True),
        ForeignKey("routine_time_blocks.id", ondelete="CASCADE"),
        nullable=False,
    )
    session_type = Column(SessionTypeEnum, nullable=False)
    # Polymorphic: a real Postgres UUID (Plan/Series/Accumulator/collection id)
    # for every session_type except RECITATION, where it can also be a
    # non-UUID pecha-style text id.
    source_id = Column(String(255), nullable=True)
    duration_ms = Column(Integer, nullable=True)
    display_order = Column(Integer, nullable=False)

    created_at = Column(
        DateTime(timezone=True),
        default=datetime.now(_datetime.timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True), default=datetime.now(_datetime.timezone.utc)
    )

    __table_args__ = (Index("idx_sessions_time_block", "time_block_id"),)
