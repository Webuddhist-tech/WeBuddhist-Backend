from uuid import uuid4

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UUID,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB

from ..db.database import Base


class LiveEditionSettings(Base):
    """What the live controller shows for one library edition, set in Studio.

    One row per edition, not per event: every event that recites the edition
    reads the same short titles, repeated segments and return jumps. Each list
    is stored whole, because Studio and the JSON import both replace a list at
    once rather than editing its rows one by one.
    """

    __tablename__ = "live_edition_settings"

    # A library edition id, e.g. "Zt5c0fe1OMJI1Kh8rp2FM".
    edition_id = Column(String(64), primary_key=True)
    # [{"section_id", "title", "icon"}]
    short_titles = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # [{"segment_id", "times"}]
    repeated_segments = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    # [{"key", "after_segment_id", "to_segment_id", "times", "label": {lang: text}}]
    return_jumps = Column(JSONB, nullable=False, server_default=text("'[]'::jsonb"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_by = Column(String(255), nullable=True)


class EventLiveSettings(Base):
    """The room settings every controller of one event uses."""

    __tablename__ = "event_live_settings"

    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    followed_languages = Column(ARRAY(String(16)), nullable=False, server_default=text("'{}'"))
    # The language a recitation is read in when its edition names none.
    fallback_language = Column(String(16), nullable=True)
    record_play_times = Column(Boolean, nullable=False, server_default=text("true"))
    lead_max_ms = Column(Integer, nullable=False, server_default=text("2000"))
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    updated_by = Column(String(255), nullable=True)


class EventLiveController(Base):
    """One device allowed to drive an event's recitation.

    Only a hash of the token is kept: the operator enters the token once on the
    device, so the backend never has to hand it back.
    """

    __tablename__ = "event_live_controllers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=False,
    )
    name = Column(String(120), nullable=False)
    # sha256 hex of the token; unique so one token can never drive two events.
    token_hash = Column(String(64), nullable=False, unique=True)
    # The token's last characters, so Studio can tell two controllers apart.
    token_hint = Column(String(8), nullable=False)
    # Opened on load when the room has no open text.
    default_text_id = Column(String(255), nullable=True)
    created_by = Column(String(255), nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("idx_event_live_controllers_event", "event_id"),)


class EventLiveSectionOrder(Base):
    """The order an operator dragged an edition's sections into for one event.

    Written by the controller, so every controller of the event and a reload
    show the same order. No row means the table of contents' own order.
    """

    __tablename__ = "event_live_section_orders"

    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        primary_key=True,
    )
    edition_id = Column(String(64), primary_key=True)
    section_ids = Column(ARRAY(String(64)), nullable=False)
    updated_at = Column(DateTime(timezone=True), nullable=False, server_default=text("now()"))
