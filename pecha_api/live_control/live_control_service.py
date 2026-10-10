"""Live control settings: what Studio sets and the live controller reads.

- Per edition: short titles, repeated segments and return jumps.
- Per event: the room settings, the controllers and their tokens, and the
  order an operator dragged an edition's sections into.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.db.database import SessionLocal
from pecha_api.events.event_model import Event
from pecha_api.events.event_repository import get_event_by_id
from pecha_api.plans.authors.plan_authors_model import Author
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.plans.shared.permissions import require_cms_write_access

from . import live_control_library as library
from .live_control_auth import generate_token, hash_token, token_hint
from .live_control_models import EventLiveController, EventLiveSettings, LiveEditionSettings
from .live_control_repository import (
    add_controller,
    get_controller,
    get_edition_settings,
    get_event_settings,
    get_section_order,
    list_controllers,
    set_section_order,
    token_hash_taken,
    upsert_edition_settings,
    upsert_event_settings,
)
from .live_control_response_models import (
    ControllerDTO,
    ControllersResponse,
    ControllerWithTokenDTO,
    CreateControllerRequest,
    EditionLiveSettingsDTO,
    EditionLiveSettingsInput,
    EventLiveSettingsDTO,
    EventLiveSettingsInput,
    ImportIssue,
    RepeatedSegment,
    ReturnJump,
    ShortTitle,
    UpdateControllerRequest,
)

logger = logging.getLogger(__name__)

# What a controller used before Studio held these, so an event with no saved
# settings behaves as it always has.
DEFAULT_FOLLOWED_LANGUAGES = ["bo", "en", "zh"]
DEFAULT_FALLBACK_LANGUAGE = "bo"
DEFAULT_RECORD_PLAY_TIMES = True
DEFAULT_LEAD_MAX_MS = 2000

EDITION_LISTS = ("short_titles", "repeated_segments", "return_jumps")


def _not_found(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)


def _bad_request(detail) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


# --- Access ------------------------------------------------------------------


def load_event_or_404(db: Session, event_id: UUID) -> Event:
    event = get_event_by_id(db, event_id)
    if event is None:
        raise _not_found(f"Event with id '{event_id}' not found")
    return event


def require_event_editor(db: Session, event_id: UUID, author: Author) -> Event:
    """The event, when this author may edit it in Studio."""
    # Imported here: event_service pulls in most of the events package.
    from pecha_api.events.event_service import _require_can_edit_event

    event = load_event_or_404(db, event_id)
    _require_can_edit_event(db=db, group_id=event.group_id, author=author)
    return event


def author_for_event(token: str, event_id: UUID) -> Author:
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_event_editor(db, event_id, author)
    return author


def cms_writer(token: str) -> Author:
    """Edition settings are shared by every event that recites the edition, so
    any Studio author who may write content may set them."""
    author = validate_cms_author_details(token=token)
    require_cms_write_access(author)
    return author


def actor_name(author: Author) -> str:
    return str(getattr(author, "email", None) or author.id)


# --- Edition settings --------------------------------------------------------


def edition_settings_dto(edition_id: str, row: Optional[LiveEditionSettings]) -> EditionLiveSettingsDTO:
    if row is None:
        return EditionLiveSettingsDTO(
            edition_id=edition_id, short_titles=[], repeated_segments=[], return_jumps=[]
        )
    return EditionLiveSettingsDTO(
        edition_id=edition_id,
        short_titles=[ShortTitle.model_validate(item) for item in row.short_titles or []],
        repeated_segments=[RepeatedSegment.model_validate(item) for item in row.repeated_segments or []],
        return_jumps=[ReturnJump.model_validate(item) for item in row.return_jumps or []],
        updated_at=row.updated_at,
    )


def read_edition_settings(edition_id: str) -> EditionLiveSettingsDTO:
    with SessionLocal() as db:
        return edition_settings_dto(edition_id, get_edition_settings(db, edition_id))


async def check_edition_lists(
    edition_id: str, lists: EditionLiveSettingsInput, path: str = ""
) -> List[ImportIssue]:
    """What in these lists does not belong to the edition. Empty when all of it
    does. Only the library calls a list needs are made."""
    issues: List[ImportIssue] = []

    def issue(where: str, message: str) -> None:
        issues.append(ImportIssue(path=f"{path}{where}", message=message))

    try:
        await library.fetch_edition_info(edition_id)
    except library.EditionNotFound:
        issue("edition_id", f"edition '{edition_id}' is not in the library")
        return issues

    if lists.short_titles:
        section_ids = {section.id for section in await library.fetch_toc_sections(edition_id)}
        for index, item in enumerate(lists.short_titles):
            if item.section_id not in section_ids:
                issue(f"short_titles[{index}].section_id", "not a section of this edition")

    if lists.repeated_segments or lists.return_jumps:
        order = await library.fetch_segment_order(edition_id)
        for index, item in enumerate(lists.repeated_segments or []):
            if item.segment_id not in order:
                issue(f"repeated_segments[{index}].segment_id", "not in this edition")
        for index, jump in enumerate(lists.return_jumps or []):
            after = order.get(jump.after_segment_id)
            to = order.get(jump.to_segment_id)
            if after is None:
                issue(f"return_jumps[{index}].after_segment_id", "not in this edition")
            if to is None:
                issue(f"return_jumps[{index}].to_segment_id", "not in this edition")
            if after is not None and to is not None and to > after:
                issue(
                    f"return_jumps[{index}].to_segment_id",
                    "a return jumps back: this segment comes after the one it sits after",
                )
    return issues


def edition_lists_to_store(lists: EditionLiveSettingsInput) -> Dict[str, list]:
    """The lists given, ready for the JSONB columns. Short titles with neither a
    title nor an icon are dropped: they say nothing."""
    stored: Dict[str, list] = {}
    if lists.short_titles is not None:
        stored["short_titles"] = [
            item.model_dump() for item in lists.short_titles if item.title or item.icon
        ]
    if lists.repeated_segments is not None:
        stored["repeated_segments"] = [item.model_dump() for item in lists.repeated_segments]
    if lists.return_jumps is not None:
        stored["return_jumps"] = [item.model_dump() for item in lists.return_jumps]
    return stored


async def update_edition_settings_service(
    token: str, edition_id: str, request: EditionLiveSettingsInput
) -> EditionLiveSettingsDTO:
    author = await run_in_threadpool(cms_writer, token)
    issues = await check_edition_lists(edition_id, request)
    if issues:
        raise _bad_request([issue.model_dump() for issue in issues])

    def save() -> EditionLiveSettingsDTO:
        with SessionLocal() as db:
            lists = edition_lists_to_store(request)
            if lists:
                upsert_edition_settings(db, edition_id, lists, actor_name(author))
                db.commit()
            return edition_settings_dto(edition_id, get_edition_settings(db, edition_id))

    return await run_in_threadpool(save)


# --- Event settings ----------------------------------------------------------


def event_settings_dto(event_id: UUID, row: Optional[EventLiveSettings]) -> EventLiveSettingsDTO:
    if row is None:
        return EventLiveSettingsDTO(
            event_id=event_id,
            followed_languages=list(DEFAULT_FOLLOWED_LANGUAGES),
            fallback_language=DEFAULT_FALLBACK_LANGUAGE,
            record_play_times=DEFAULT_RECORD_PLAY_TIMES,
            lead_max_ms=DEFAULT_LEAD_MAX_MS,
        )
    return EventLiveSettingsDTO(
        event_id=event_id,
        followed_languages=list(row.followed_languages or []),
        fallback_language=row.fallback_language,
        record_play_times=row.record_play_times,
        lead_max_ms=row.lead_max_ms,
        updated_at=row.updated_at,
    )


def read_event_settings(event_id: UUID) -> EventLiveSettingsDTO:
    with SessionLocal() as db:
        load_event_or_404(db, event_id)
        return event_settings_dto(event_id, get_event_settings(db, event_id))


def event_settings_fields(
    current: EventLiveSettingsDTO, request: EventLiveSettingsInput
) -> Dict[str, object]:
    """Every column, the request's values over the current ones, so the first
    save of an event writes the defaults for whatever it leaves out."""
    given = request.model_dump(exclude_unset=True)
    return {
        "followed_languages": given.get("followed_languages", current.followed_languages) or [],
        "fallback_language": given.get("fallback_language", current.fallback_language),
        "record_play_times": (
            given["record_play_times"]
            if given.get("record_play_times") is not None
            else current.record_play_times
        ),
        "lead_max_ms": (
            given["lead_max_ms"] if given.get("lead_max_ms") is not None else current.lead_max_ms
        ),
    }


def write_event_settings(db: Session, event_id: UUID, request: EventLiveSettingsInput, actor: str) -> None:
    current = event_settings_dto(event_id, get_event_settings(db, event_id))
    upsert_event_settings(db, event_id, event_settings_fields(current, request), actor)


def update_event_settings_service(
    token: str, event_id: UUID, request: EventLiveSettingsInput
) -> EventLiveSettingsDTO:
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_event_editor(db, event_id, author)
        write_event_settings(db, event_id, request, actor_name(author))
        db.commit()
        return event_settings_dto(event_id, get_event_settings(db, event_id))


def get_event_settings_service(token: str, event_id: UUID) -> EventLiveSettingsDTO:
    author_for_event(token, event_id)
    return read_event_settings(event_id)


# --- Controllers -------------------------------------------------------------


def _controller_dto(controller: EventLiveController) -> ControllerDTO:
    return ControllerDTO(
        id=controller.id,
        event_id=controller.event_id,
        name=controller.name,
        token_hint=controller.token_hint,
        default_text_id=controller.default_text_id,
        created_by=controller.created_by,
        created_at=controller.created_at,
        last_used_at=controller.last_used_at,
        revoked_at=controller.revoked_at,
    )


def _with_token(controller: EventLiveController, token: str) -> ControllerWithTokenDTO:
    return ControllerWithTokenDTO(**_controller_dto(controller).model_dump(), token=token)


def _new_token(db: Session, requested: Optional[str]) -> Tuple[str, str]:
    """A token and its hash. A token the author typed must not already be in
    use - by any event, since tokens are looked up by hash alone."""
    token = requested or generate_token()
    token_hash = hash_token(token)
    if token_hash_taken(db, token_hash):
        if requested:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This token is already in use; choose another",
            )
        token = generate_token()
        token_hash = hash_token(token)
    return token, token_hash


def list_controllers_service(token: str, event_id: UUID) -> ControllersResponse:
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_event_editor(db, event_id, author)
        return ControllersResponse(
            controllers=[_controller_dto(c) for c in list_controllers(db, event_id)]
        )


def create_controller_service(
    token: str, event_id: UUID, request: CreateControllerRequest
) -> ControllerWithTokenDTO:
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_event_editor(db, event_id, author)
        controller_token, token_hash = _new_token(db, request.token)
        controller = add_controller(
            db,
            EventLiveController(
                event_id=event_id,
                name=request.name.strip(),
                token_hash=token_hash,
                token_hint=token_hint(controller_token),
                default_text_id=(request.default_text_id or "").strip() or None,
                created_by=actor_name(author),
                created_at=datetime.now(timezone.utc),
            ),
        )
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This token is already in use; choose another",
            )
        db.refresh(controller)
        return _with_token(controller, controller_token)


def update_controller_service(
    token: str, event_id: UUID, controller_id: UUID, request: UpdateControllerRequest
) -> ControllerDTO:
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_event_editor(db, event_id, author)
        controller = get_controller(db, event_id, controller_id)
        if controller is None:
            raise _not_found(f"Controller with id '{controller_id}' not found")
        if controller.revoked_at is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A revoked controller cannot be changed",
            )
        given = request.model_fields_set
        if "name" in given and request.name:
            controller.name = request.name.strip()
        if "default_text_id" in given:
            controller.default_text_id = (request.default_text_id or "").strip() or None
        new_token: Optional[str] = None
        if request.token or request.regenerate_token:
            new_token, controller.token_hash = _new_token(db, request.token)
            controller.token_hint = token_hint(new_token)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This token is already in use; choose another",
            )
        db.refresh(controller)
        return _with_token(controller, new_token) if new_token else _controller_dto(controller)


def revoke_controller_service(token: str, event_id: UUID, controller_id: UUID) -> None:
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_event_editor(db, event_id, author)
        controller = get_controller(db, event_id, controller_id)
        if controller is None:
            raise _not_found(f"Controller with id '{controller_id}' not found")
        if controller.revoked_at is None:
            controller.revoked_at = datetime.now(timezone.utc)
            db.commit()


# --- Section order (written by the controller) -------------------------------


def read_section_order(event_id: UUID, edition_id: str) -> List[str]:
    with SessionLocal() as db:
        row = get_section_order(db, event_id, edition_id)
        return list(row.section_ids) if row else []


def write_section_order(event_id: UUID, edition_id: str, section_ids: List[str]) -> List[str]:
    with SessionLocal() as db:
        load_event_or_404(db, event_id)
        set_section_order(db, event_id, edition_id, list(dict.fromkeys(section_ids)))
        db.commit()
        row = get_section_order(db, event_id, edition_id)
        return list(row.section_ids) if row else []
