from datetime import datetime
from typing import Dict, List, Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Times a passage or a segment can be set to; the controller's old cap.
MAX_TIMES = 21
# Phone lead: 0 to 10 s in 50 ms steps.
MAX_LEAD_MS = 10_000
LEAD_STEP_MS = 50

SETTINGS_FILE_FORMAT = "webuddhist-live-control-settings"
SETTINGS_FILE_VERSION = 1

_ID = Field(min_length=1, max_length=64)


def _lower(value: object) -> object:
    return value.strip().lower() if isinstance(value, str) else value


class _Strict(BaseModel):
    """Unknown keys are refused, so a typo in an imported file is reported
    rather than silently dropped."""

    model_config = ConfigDict(extra="forbid")


class ShortTitle(_Strict):
    section_id: str = _ID
    title: str = Field(default="", max_length=120)
    icon: str = Field(default="", max_length=16)
    # The section's own title, written into templates so whoever fills one in
    # can see which section a row is. Never stored.
    section_title: Optional[str] = Field(default=None, exclude=True)

    @field_validator("title", "icon", mode="before")
    @classmethod
    def _strip(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value


class RepeatedSegment(_Strict):
    segment_id: str = _ID
    times: int = Field(ge=2, le=MAX_TIMES)


class ReturnJump(_Strict):
    # Shared by every language edition of a text, so a return's count follows
    # it when the room switches edition.
    key: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_.-]+$")
    after_segment_id: str = _ID
    to_segment_id: str = _ID
    times: int = Field(ge=1, le=MAX_TIMES)
    label: Dict[str, str] = Field(default_factory=dict)

    @field_validator("label")
    @classmethod
    def _labels(cls, value: Dict[str, str]) -> Dict[str, str]:
        cleaned: Dict[str, str] = {}
        for language, text in value.items():
            language = language.strip().lower()
            if not language or len(language) > 16:
                raise ValueError("label languages are codes such as en, bo, zh")
            if len(text) > 200:
                raise ValueError(f"label '{language}' is longer than 200 characters")
            cleaned[language] = text.strip()
        return cleaned


def _unique(items: list, attribute: str, what: str) -> list:
    seen = set()
    for item in items:
        value = getattr(item, attribute)
        if value in seen:
            raise ValueError(f"{what} '{value}' is listed twice")
        seen.add(value)
    return items


class EditionLiveSettingsInput(_Strict):
    """An edition's lists. A list left out (None) is kept as it is."""

    short_titles: Optional[List[ShortTitle]] = None
    repeated_segments: Optional[List[RepeatedSegment]] = None
    return_jumps: Optional[List[ReturnJump]] = None

    @field_validator("short_titles")
    @classmethod
    def _unique_sections(cls, value):
        return value if value is None else _unique(value, "section_id", "section")

    @field_validator("repeated_segments")
    @classmethod
    def _unique_segments(cls, value):
        return value if value is None else _unique(value, "segment_id", "segment")

    @field_validator("return_jumps")
    @classmethod
    def _unique_jumps(cls, value):
        if value is None:
            return value
        _unique(value, "key", "return key")
        return _unique(value, "after_segment_id", "after segment")


class EditionLiveSettingsDTO(BaseModel):
    edition_id: str
    short_titles: List[ShortTitle]
    repeated_segments: List[RepeatedSegment]
    return_jumps: List[ReturnJump]
    updated_at: Optional[datetime] = None


class EventLiveSettingsInput(_Strict):
    followed_languages: Optional[List[str]] = None
    fallback_language: Optional[str] = None
    record_play_times: Optional[bool] = None
    lead_max_ms: Optional[int] = Field(default=None, ge=0, le=MAX_LEAD_MS)

    @field_validator("followed_languages", mode="before")
    @classmethod
    def _languages(cls, value: object) -> object:
        if not isinstance(value, list):
            return value
        languages: List[str] = []
        for language in value:
            language = _lower(language)
            if not isinstance(language, str) or not 2 <= len(language) <= 16:
                raise ValueError("languages are codes such as en, bo, zh")
            if language not in languages:
                languages.append(language)
        return languages

    @field_validator("fallback_language", mode="before")
    @classmethod
    def _fallback(cls, value: object) -> object:
        value = _lower(value)
        if value == "":
            return None
        if value is not None and (not isinstance(value, str) or not 2 <= len(value) <= 16):
            raise ValueError("the fallback language is a code such as bo")
        return value

    @field_validator("lead_max_ms")
    @classmethod
    def _lead_step(cls, value: Optional[int]) -> Optional[int]:
        if value is not None and value % LEAD_STEP_MS:
            raise ValueError(f"lead_max_ms goes in steps of {LEAD_STEP_MS}")
        return value


class EventLiveSettingsDTO(BaseModel):
    event_id: UUID
    followed_languages: List[str]
    fallback_language: Optional[str] = None
    record_play_times: bool
    lead_max_ms: int
    updated_at: Optional[datetime] = None


# --- Controllers -----------------------------------------------------------

_TOKEN = Field(default=None, min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_.~-]+$")


class CreateControllerRequest(_Strict):
    name: str = Field(min_length=1, max_length=120)
    # Left out: the backend generates one.
    token: Optional[str] = _TOKEN
    default_text_id: Optional[str] = Field(default=None, max_length=255)


class UpdateControllerRequest(_Strict):
    """Only the fields sent are changed. `default_text_id: null` clears it."""

    name: Optional[str] = Field(default=None, min_length=1, max_length=120)
    token: Optional[str] = _TOKEN
    regenerate_token: bool = False
    default_text_id: Optional[str] = Field(default=None, max_length=255)


class ControllerDTO(BaseModel):
    id: UUID
    event_id: UUID
    name: str
    token_hint: str
    default_text_id: Optional[str] = None
    created_by: str
    created_at: datetime
    last_used_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None


class ControllerWithTokenDTO(ControllerDTO):
    """Returned only when a token is set: the one time Studio sees it."""

    token: str


class ControllersResponse(BaseModel):
    controllers: List[ControllerDTO]


class ControllerSelfDTO(BaseModel):
    """What a controller learns about itself from its own token."""

    id: Optional[UUID] = None
    event_id: UUID
    name: Optional[str] = None
    default_text_id: Optional[str] = None


# --- Plan texts ------------------------------------------------------------


class PlanTextDTO(BaseModel):
    text_id: str
    title: Optional[str] = None
    language: Optional[str] = None
    plan_id: UUID
    day_number: int
    display_order: int


class PlanTextsResponse(BaseModel):
    event_id: UUID
    plan_id: Optional[UUID] = None
    series_id: Optional[UUID] = None
    texts: List[PlanTextDTO]


# --- Import / export -------------------------------------------------------


class SettingsFileEdition(EditionLiveSettingsInput):
    edition_id: str = _ID


class SettingsFile(_Strict):
    format: Literal["webuddhist-live-control-settings"]
    version: Literal[1]
    event: Optional[EventLiveSettingsInput] = None
    editions: List[SettingsFileEdition] = Field(default_factory=list)

    @field_validator("editions")
    @classmethod
    def _unique_editions(cls, value):
        return _unique(value, "edition_id", "edition")


class ImportIssue(BaseModel):
    path: str
    message: str


class ImportEditionSummary(BaseModel):
    edition_id: str
    short_titles: Optional[int] = None
    repeated_segments: Optional[int] = None
    return_jumps: Optional[int] = None


class ImportReport(BaseModel):
    ok: bool
    applied: bool
    editions: List[ImportEditionSummary] = Field(default_factory=list)
    event: Optional[EventLiveSettingsInput] = None
    errors: List[ImportIssue] = Field(default_factory=list)


# --- AI ----------------------------------------------------------------------


class ShortTitleSuggestion(BaseModel):
    section_id: str
    section_title: Optional[str] = None
    title: str
    icon: str


class ShortTitleSuggestionsResponse(BaseModel):
    edition_id: str
    language: Optional[str] = None
    suggestions: List[ShortTitleSuggestion]
