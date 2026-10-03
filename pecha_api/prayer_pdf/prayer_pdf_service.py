from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, Optional, Tuple
from uuid import UUID
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.chat.repository import get_room_by_event_id, get_room_by_group_id
from pecha_api.db.database import SessionLocal
from pecha_api.events.event_repository import get_event_by_id
from pecha_api.plans.authors.plan_authors_model import Author
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole
from pecha_api.plans.groups.groups_repository import get_group_by_id
from pecha_api.plans.shared.permissions import (
    require_can_read_group_content,
    require_cms_write_access,
    require_group_member,
)

from .prayer_pdf_avatars import load_avatars, preview_avatar_url
from .prayer_pdf_content import (
    SAMPLE_ROWS,
    CardList,
    PrayerRow,
    build_cards,
    day_number,
    lines,
    parse_skip_messages,
    tibetan_digits,
)
from .prayer_pdf_model import PrayerPdfSettings
from .prayer_pdf_renderer import PrayerPdfDocument, RenderCard, html_to_pdf, render_html
from .prayer_pdf_repository import (
    delete_settings,
    get_event_settings,
    get_group_settings,
    list_prayer_requests,
    page_prayer_requests,
    upsert_settings,
)
from .prayer_pdf_response_models import (
    DEFAULT_TEXTS,
    DEFAULT_TIMEZONE,
    PrayerPdfPreviewResponse,
    PrayerPdfSettingsDTO,
    PrayerPdfSettingsSource,
    PrayerRequestDTO,
    PrayerRequestListResponse,
    UpdatePrayerPdfSettingsRequest,
)

NO_PRAYER_REQUESTS = "NO_PRAYER_REQUESTS"

# Who may change the layout and export the PDF: the people who run the
# group's content. The PDF carries members' names, photos and private
# requests, so viewers and platform reviewers can read the settings but not
# export.
_MANAGE_ROLES = {
    AuthorGroupMemberRole.OWNER,
    AuthorGroupMemberRole.ADMIN,
    AuthorGroupMemberRole.AUTHOR,
}

_SETTINGS_FIELDS = tuple(UpdatePrayerPdfSettingsRequest.model_fields)


@dataclass
class _Target:
    """What a PDF is built for: a group's own room, or one of its events."""

    group_id: UUID
    event_id: Optional[UUID]
    name: str


# ---------------------------------------------------------------- lookups


def _pick_en(entries, attribute: str, fallback: str) -> str:
    first = None
    for entry in entries or []:
        if first is None:
            first = entry
        language = entry.language
        code = language.value if hasattr(language, "value") else str(language)
        if code.upper() == "EN":
            return getattr(entry, attribute) or fallback
    if first is None:
        return fallback
    return getattr(first, attribute) or fallback


def _load_group_target(db: Session, group_id: UUID) -> _Target:
    group = get_group_by_id(db=db, group_id=group_id)
    if group is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Group not found")
    return _Target(group_id=group.id, event_id=None, name=_pick_en(group.metadata_entries, "title", "Group"))


def _load_event_target(db: Session, event_id: UUID) -> _Target:
    event = get_event_by_id(db=db, event_id=event_id)
    if event is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Event not found")
    return _Target(group_id=event.group_id, event_id=event.id, name=_pick_en(event.metadata_entries, "name", "Event"))


def _require_can_manage(db: Session, group_id: UUID, author: Author) -> None:
    require_group_member(db=db, group_id=group_id, author=author, allowed_roles=_MANAGE_ROLES)


def _resolve_settings(
    db: Session, target: _Target
) -> Tuple[Optional[PrayerPdfSettings], PrayerPdfSettingsSource]:
    """An event uses its own row, else its group's; a group uses its own."""
    if target.event_id is not None:
        row = get_event_settings(db, target.event_id)
        if row is not None:
            return row, PrayerPdfSettingsSource.EVENT
    row = get_group_settings(db, target.group_id)
    if row is not None:
        return row, PrayerPdfSettingsSource.GROUP
    return None, PrayerPdfSettingsSource.DEFAULT


def _settings_dto(
    target: _Target, row: Optional[PrayerPdfSettings], source: PrayerPdfSettingsSource
) -> PrayerPdfSettingsDTO:
    base = {"group_id": target.group_id, "event_id": target.event_id, "source": source}
    if row is None:
        return PrayerPdfSettingsDTO(
            **base,
            **DEFAULT_TEXTS,
            subtitle=f"Prayer requests received during {target.name}",
        )
    return PrayerPdfSettingsDTO(
        **base,
        **{name: getattr(row, name) for name in _SETTINGS_FIELDS},
        updated_at=row.updated_at,
        updated_by=row.updated_by,
    )


# --------------------------------------------------------------- settings


def _get_settings(token: str, load_target) -> PrayerPdfSettingsDTO:
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        target = load_target(db)
        require_can_read_group_content(db=db, group_id=target.group_id, author=author)
        row, source = _resolve_settings(db, target)
        return _settings_dto(target, row, source)


def _update_settings(token: str, load_target, request: UpdatePrayerPdfSettingsRequest) -> PrayerPdfSettingsDTO:
    author = validate_cms_author_details(token=token)
    require_cms_write_access(author)
    with SessionLocal() as db:
        target = load_target(db)
        _require_can_manage(db, target.group_id, author)
        row = upsert_settings(
            db,
            group_id=target.group_id,
            event_id=target.event_id,
            values=request.model_dump(include=set(_SETTINGS_FIELDS)),
            updated_by=author.email,
        )
        source = PrayerPdfSettingsSource.EVENT if target.event_id else PrayerPdfSettingsSource.GROUP
        return _settings_dto(target, row, source)


def _reset_settings(token: str, load_target) -> PrayerPdfSettingsDTO:
    """Drop this target's own row: an event falls back to its group's
    settings, a group to the defaults."""
    author = validate_cms_author_details(token=token)
    require_cms_write_access(author)
    with SessionLocal() as db:
        target = load_target(db)
        _require_can_manage(db, target.group_id, author)
        own = (
            get_event_settings(db, target.event_id)
            if target.event_id is not None
            else get_group_settings(db, target.group_id)
        )
        if own is not None:
            delete_settings(db, own)
        row, source = _resolve_settings(db, target)
        return _settings_dto(target, row, source)


def get_group_prayer_pdf_settings_service(token: str, group_id: UUID) -> PrayerPdfSettingsDTO:
    return _get_settings(token, lambda db: _load_group_target(db, group_id))


def update_group_prayer_pdf_settings_service(
    token: str, group_id: UUID, request: UpdatePrayerPdfSettingsRequest
) -> PrayerPdfSettingsDTO:
    return _update_settings(token, lambda db: _load_group_target(db, group_id), request)


def reset_group_prayer_pdf_settings_service(token: str, group_id: UUID) -> PrayerPdfSettingsDTO:
    return _reset_settings(token, lambda db: _load_group_target(db, group_id))


def get_event_prayer_pdf_settings_service(token: str, event_id: UUID) -> PrayerPdfSettingsDTO:
    return _get_settings(token, lambda db: _load_event_target(db, event_id))


def update_event_prayer_pdf_settings_service(
    token: str, event_id: UUID, request: UpdatePrayerPdfSettingsRequest
) -> PrayerPdfSettingsDTO:
    return _update_settings(token, lambda db: _load_event_target(db, event_id), request)


def reset_event_prayer_pdf_settings_service(token: str, event_id: UUID) -> PrayerPdfSettingsDTO:
    return _reset_settings(token, lambda db: _load_event_target(db, event_id))


# ------------------------------------------------------------------- PDF


@dataclass
class PrayerPdfFile:
    content: bytes
    filename: str
    prayer_count: int


def day_window_utc(day: date, tz_name: str) -> Tuple[datetime, datetime]:
    """[start, end) of a calendar day in `tz_name`, as UTC instants. Built
    from both midnights so a DST change inside the day is honoured."""
    zone = ZoneInfo(tz_name)
    start = datetime.combine(day, time.min, tzinfo=zone)
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=zone)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _posted_by(user) -> str:
    """trim(firstname || ' ' || coalesce(lastname, '')), as the action exported it."""
    return f"{user.firstname or ''} {user.lastname or ''}".strip()


def _room(db: Session, target: _Target):
    return (
        get_room_by_event_id(db=db, event_id=target.event_id)
        if target.event_id is not None
        else get_room_by_group_id(db=db, group_id=target.group_id)
    )


def _room_rows(db: Session, target: _Target, day: date, tz_name: str):
    room = _room(db, target)
    if room is None:
        return []
    start_utc, end_utc = day_window_utc(day, tz_name)
    return list_prayer_requests(db, room_id=room.id, start_utc=start_utc, end_utc=end_utc)


def _cards_from_rows(rows, settings) -> CardList:
    return build_cards(
        (PrayerRow(user_id=str(user.id), posted_by=_posted_by(user), message=message.body) for message, user in rows),
        skip=parse_skip_messages(settings.skip_messages),
        columns=settings.columns,
    )


def _document(settings, card_list: CardList, avatars: Dict[str, Optional[str]], day: date) -> PrayerPdfDocument:
    """`settings` is anything with the settings fields: the saved DTO when
    printing, the unsaved form when previewing."""
    number = day_number(day, settings.day_one)
    return PrayerPdfDocument(
        title_bo=settings.title_bo,
        title=settings.title,
        title_zh=settings.title_zh,
        subtitle_bo=settings.subtitle_bo,
        subtitle=settings.subtitle,
        subtitle_zh=settings.subtitle_zh,
        date_label=f"{day.day} {day:%B %Y}",
        zh_date=f"{day.year}年{day.month}月{day.day}日",
        day_number=number,
        day_number_bo=tibetan_digits(number),
        closing_bo=lines(settings.closing_bo),
        closing_mantra=settings.closing_mantra,
        closing_zh=lines(settings.closing_zh),
        closing_en=lines(settings.closing_en),
        closing_emoji=settings.closing_emoji,
        page_size=settings.page_size,
        columns=settings.columns,
        primary_color=settings.primary_color,
        secondary_color=settings.secondary_color,
        cards=[RenderCard(card=card, avatar=avatars.get(card.user_id)) for card in card_list.cards],
    )


def _today(tz_name: Optional[str]) -> date:
    return datetime.now(ZoneInfo(tz_name or DEFAULT_TIMEZONE)).date()


def _build_document(db: Session, target: _Target, day: Optional[date]) -> Tuple[PrayerPdfDocument, date]:
    row, _ = _resolve_settings(db, target)
    settings = _settings_dto(target, row, PrayerPdfSettingsSource.DEFAULT)
    day = day or _today(settings.timezone)

    rows = _room_rows(db, target, day, settings.timezone)
    card_list = _cards_from_rows(rows, settings)
    if not card_list.cards:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=NO_PRAYER_REQUESTS)

    avatar_urls = {str(user.id): user.avatar_url for _, user in rows}
    avatars = load_avatars((card.user_id, avatar_urls.get(card.user_id)) for card in card_list.cards)
    return _document(settings, card_list, avatars, day), day


def _prepare(token: str, load_target, day: Optional[date]) -> Tuple[PrayerPdfDocument, str]:
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        target = load_target(db)
        _require_can_manage(db, target.group_id, author)
        document, day = _build_document(db, target, day)
        return document, f"Prayer_Requests_{day.isoformat()}_{document.page_size}.pdf"


async def _render(token: str, load_target, day: Optional[date]) -> PrayerPdfFile:
    # Auth, queries and avatar downloads block; keep them off the event loop.
    document, filename = await run_in_threadpool(_prepare, token, load_target, day)
    content = await html_to_pdf(
        render_html(document),
        date_label=document.date_label,
        color=document.secondary_color,
    )
    return PrayerPdfFile(content=content, filename=filename, prayer_count=len(document.cards))


# --------------------------------------------------------------- preview


def _preview(
    token: str, load_target, request: UpdatePrayerPdfSettingsRequest, day: Optional[date]
) -> PrayerPdfPreviewResponse:
    """The page as the PDF would print it with these (unsaved) settings, as
    HTML for the Studio to show. Uses that day's requests, or samples when
    there are none. Photos are linked rather than downloaded and checked, so
    a generated letter avatar can show here that the PDF would replace with
    initials."""
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        target = load_target(db)
        _require_can_manage(db, target.group_id, author)
        day = day or _today(request.timezone)
        rows = _room_rows(db, target, day, request.timezone)
        card_list = _cards_from_rows(rows, request)
        is_sample = not card_list.cards
        if is_sample:
            card_list = build_cards(SAMPLE_ROWS, skip=set(), columns=request.columns)
            avatars = {}
        else:
            avatar_urls = {str(user.id): user.avatar_url for _, user in rows}
            avatars = {card.user_id: preview_avatar_url(avatar_urls.get(card.user_id)) for card in card_list.cards}
        document = _document(request, card_list, avatars, day)
        return PrayerPdfPreviewResponse(
            html=render_html(document, preview=True),
            day=day,
            prayer_count=0 if is_sample else len(card_list.cards),
            is_sample=is_sample,
        )


def preview_group_prayer_pdf_service(
    token: str, group_id: UUID, request: UpdatePrayerPdfSettingsRequest, day: Optional[date]
) -> PrayerPdfPreviewResponse:
    return _preview(token, lambda db: _load_group_target(db, group_id), request, day)


def preview_event_prayer_pdf_service(
    token: str, event_id: UUID, request: UpdatePrayerPdfSettingsRequest, day: Optional[date]
) -> PrayerPdfPreviewResponse:
    return _preview(token, lambda db: _load_event_target(db, event_id), request, day)


async def build_group_prayer_pdf_service(token: str, group_id: UUID, day: Optional[date]) -> PrayerPdfFile:
    return await _render(token, lambda db: _load_group_target(db, group_id), day)


async def build_event_prayer_pdf_service(token: str, event_id: UUID, day: Optional[date]) -> PrayerPdfFile:
    return await _render(token, lambda db: _load_event_target(db, event_id), day)


# ------------------------------------------------------------------- list


def _list_requests(
    token: str, load_target, day: Optional[date], skip: int, limit: int
) -> PrayerRequestListResponse:
    """The room's prayer requests as posted, newest first: one day's (in the
    settings' timezone) or, without a day, every day's. Same access as the
    PDF, since it shows the same names and requests."""
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        target = load_target(db)
        _require_can_manage(db, target.group_id, author)
        row, _ = _resolve_settings(db, target)
        tz_name = row.timezone if row is not None and row.timezone else DEFAULT_TIMEZONE
        room = _room(db, target)
        rows, total = [], 0
        if room is not None:
            start_utc, end_utc = day_window_utc(day, tz_name) if day is not None else (None, None)
            rows, total = page_prayer_requests(
                db, room_id=room.id, start_utc=start_utc, end_utc=end_utc, skip=skip, limit=limit
            )
        return PrayerRequestListResponse(
            items=[
                PrayerRequestDTO(
                    id=message.id,
                    user_id=user.id,
                    posted_by=_posted_by(user),
                    avatar_url=preview_avatar_url(user.avatar_url),
                    message=message.body,
                    intention=message.intention,
                    is_edited=bool(message.is_edited),
                    created_at=message.created_at,
                )
                for message, user in rows
            ],
            total=total,
            skip=skip,
            limit=limit,
            day=day,
            timezone=tz_name,
        )


def list_group_prayer_requests_service(
    token: str, group_id: UUID, day: Optional[date], skip: int, limit: int
) -> PrayerRequestListResponse:
    return _list_requests(token, lambda db: _load_group_target(db, group_id), day, skip, limit)


def list_event_prayer_requests_service(
    token: str, event_id: UUID, day: Optional[date], skip: int, limit: int
) -> PrayerRequestListResponse:
    return _list_requests(token, lambda db: _load_event_target(db, event_id), day, skip, limit)
