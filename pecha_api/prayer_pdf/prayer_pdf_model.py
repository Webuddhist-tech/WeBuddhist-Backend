from datetime import datetime
import datetime as _datetime
from uuid import uuid4

from sqlalchemy import (
    CheckConstraint,
    Column,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import UUID

from pecha_api.db.database import Base


class PrayerPdfSettings(Base):
    """The wording and layout of the printable prayer-request PDF, per group
    or per event.

    A row with only `group_id` is the group's template, used for the group's
    own chat room and for any of its events that have no row of their own.
    A row with `event_id` is that event's override; `group_id` is the event's
    group, kept so the row is gated by the same group membership checks.

    Text columns are printed as stored: an empty one is left off the page.
    Multi-line columns hold one printed line per line."""

    __tablename__ = "prayer_pdf_settings"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid4)
    group_id = Column(
        UUID(as_uuid=True),
        ForeignKey("author_groups.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_id = Column(
        UUID(as_uuid=True),
        ForeignKey("events.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Header, top to bottom: Tibetan title, title, Chinese title, then the
    # Tibetan, English and Chinese subtitles.
    title_bo = Column(String(255), nullable=True)
    title = Column(String(255), nullable=True)
    title_zh = Column(String(255), nullable=True)
    subtitle_bo = Column(Text, nullable=True)
    subtitle = Column(Text, nullable=True)
    subtitle_zh = Column(Text, nullable=True)
    # The "Day: n" badge counts from this date; no date, no badge.
    day_one = Column(Date, nullable=True)

    # Closing block after the last card.
    closing_bo = Column(Text, nullable=True)
    closing_mantra = Column(Text, nullable=True)
    closing_zh = Column(Text, nullable=True)
    closing_en = Column(Text, nullable=True)
    closing_emoji = Column(String(64), nullable=True)

    # Exact messages (case-insensitive) that are app feedback, not prayers.
    skip_messages = Column(Text, nullable=True)

    # The day a prayer belongs to is decided in this zone.
    timezone = Column(
        String(64), nullable=False, server_default=sql_text("'Asia/Kolkata'")
    )
    page_size = Column(String(8), nullable=False, server_default=sql_text("'A3'"))
    columns = Column(Integer, nullable=False, server_default=sql_text("5"))
    primary_color = Column(
        String(16), nullable=False, server_default=sql_text("'#7a1f1f'")
    )
    secondary_color = Column(
        String(16), nullable=False, server_default=sql_text("'#b8872b'")
    )

    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(_datetime.timezone.utc),
        nullable=False,
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(_datetime.timezone.utc),
        nullable=False,
    )
    updated_by = Column(String(255), nullable=True)

    __table_args__ = (
        CheckConstraint(
            "columns BETWEEN 2 AND 6", name="ck_prayer_pdf_settings_columns"
        ),
        Index(
            "uq_prayer_pdf_settings_group",
            "group_id",
            unique=True,
            postgresql_where=sql_text("event_id IS NULL"),
        ),
        Index(
            "uq_prayer_pdf_settings_event",
            "event_id",
            unique=True,
            postgresql_where=sql_text("event_id IS NOT NULL"),
        ),
    )
