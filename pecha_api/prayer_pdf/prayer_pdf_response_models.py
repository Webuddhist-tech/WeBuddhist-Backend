from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, field_validator

PageSize = Literal["A3", "A4"]

DEFAULT_TIMEZONE = "Asia/Kolkata"
DEFAULT_PAGE_SIZE: PageSize = "A3"
DEFAULT_COLUMNS = 5
DEFAULT_PRIMARY_COLOR = "#7a1f1f"
DEFAULT_SECONDARY_COLOR = "#b8872b"

# What a group or event prints before anyone has saved settings for it: the
# generic header and blessing. Event-specific wording (which puja, the Tara
# verses) is entered in the Studio.
DEFAULT_TEXTS = {
    "title_bo": "སྐྱབས་ཞུ།",
    "title": "Prayer Requests",
    "title_zh": "迴向祈願名單",
    "subtitle_bo": None,
    "subtitle_zh": None,
    "day_one": None,
    "closing_bo": "སེམས་ཅན་ཐམས་ཅད་བདེ་བ་དང་བདེ་བའི་རྒྱུ་དང་ལྡན་པར་གྱུར་ཅིག།",
    "closing_mantra": None,
    "closing_zh": None,
    "closing_en": "May all beings have happiness and the causes of happiness.",
    "closing_emoji": "🙏🙏🙏",
    "skip_messages": "no sound la\nno video la",
}


class PrayerPdfSettingsSource(str, Enum):
    """Where the settings a PDF is built with came from."""

    EVENT = "EVENT"
    GROUP = "GROUP"
    DEFAULT = "DEFAULT"


class _PrayerPdfFields(BaseModel):
    title_bo: Optional[str] = Field(default=None, max_length=255)
    title: Optional[str] = Field(default=None, max_length=255)
    title_zh: Optional[str] = Field(default=None, max_length=255)
    subtitle_bo: Optional[str] = Field(default=None, max_length=2000)
    subtitle: Optional[str] = Field(default=None, max_length=2000)
    subtitle_zh: Optional[str] = Field(default=None, max_length=2000)
    day_one: Optional[date] = None

    closing_bo: Optional[str] = Field(default=None, max_length=5000)
    closing_mantra: Optional[str] = Field(default=None, max_length=1000)
    closing_zh: Optional[str] = Field(default=None, max_length=5000)
    closing_en: Optional[str] = Field(default=None, max_length=5000)
    closing_emoji: Optional[str] = Field(default=None, max_length=64)

    skip_messages: Optional[str] = Field(default=None, max_length=5000)

    timezone: str = Field(default=DEFAULT_TIMEZONE, max_length=64)
    page_size: PageSize = DEFAULT_PAGE_SIZE
    columns: int = Field(default=DEFAULT_COLUMNS, ge=2, le=6)
    primary_color: str = Field(default=DEFAULT_PRIMARY_COLOR, pattern=r"^#[0-9A-Fa-f]{6}$")
    secondary_color: str = Field(default=DEFAULT_SECONDARY_COLOR, pattern=r"^#[0-9A-Fa-f]{6}$")


class PrayerPdfSettingsDTO(_PrayerPdfFields):
    group_id: UUID
    event_id: Optional[UUID] = None
    source: PrayerPdfSettingsSource
    updated_at: Optional[datetime] = None
    updated_by: Optional[str] = None


_TEXT_FIELDS = (
    "title_bo",
    "title",
    "title_zh",
    "subtitle_bo",
    "subtitle",
    "subtitle_zh",
    "closing_bo",
    "closing_mantra",
    "closing_zh",
    "closing_en",
    "closing_emoji",
    "skip_messages",
)


class UpdatePrayerPdfSettingsRequest(_PrayerPdfFields):
    @field_validator(*_TEXT_FIELDS)
    @classmethod
    def _blank_to_none(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        # Line breaks are meaningful (one printed line each); only the ends trim.
        stripped = value.replace("\r\n", "\n").strip()
        return stripped or None

    @field_validator("timezone")
    @classmethod
    def _known_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"Unknown timezone '{value}'") from exc
        return value


class PrayerPdfPreviewResponse(BaseModel):
    """The page for the Studio's live preview, laid out by its own script.
    Fonts are relative URLs ("fonts/<name>") under /cms/prayer-pdf/."""

    html: str
    day: date
    # Requests on that day; 0 when the preview shows samples instead.
    prayer_count: int
    is_sample: bool
