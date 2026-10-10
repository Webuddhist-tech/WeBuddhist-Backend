"""Live control settings as one JSON file: sample, template, export, import,
and AI suggestions for short titles.

An import is checked whole before anything is written: every edition against
the library, the event block against the caller's rights. Each list given for
an edition replaces that edition's list; a list left out is not touched."""

from typing import Any, Dict, List, Optional
from uuid import UUID

from fastapi import HTTPException
from pydantic import ValidationError
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.db.database import SessionLocal
from pecha_api.external_clients.gemini_client import suggest_short_titles
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details

from . import live_control_library as library
from .live_control_models import LiveEditionSettings
from .live_control_repository import (
    get_edition_settings,
    get_event_settings,
    upsert_edition_settings,
)
from .live_control_response_models import (
    SETTINGS_FILE_FORMAT,
    SETTINGS_FILE_VERSION,
    ImportEditionSummary,
    ImportIssue,
    ImportReport,
    SettingsFile,
    ShortTitleSuggestion,
    ShortTitleSuggestionsResponse,
)
from .live_control_service import (
    actor_name,
    check_edition_lists,
    cms_writer,
    edition_lists_to_store,
    event_settings_dto,
    require_event_editor,
    write_event_settings,
)

# The longest a suggested title is asked to be: the sidebar is narrow.
SUGGESTED_TITLE_MAX_LENGTH = 32


def sample_file() -> Dict[str, Any]:
    """A filled-in example of every part of the file."""
    return {
        "format": SETTINGS_FILE_FORMAT,
        "version": SETTINGS_FILE_VERSION,
        "event": {
            "followed_languages": ["bo", "en", "zh"],
            "fallback_language": "bo",
            "record_play_times": True,
            "lead_max_ms": 2000,
        },
        "editions": [
            {
                "edition_id": "Zt5c0fe1OMJI1Kh8rp2FM",
                "short_titles": [
                    {"section_id": "gZstI2f38y2SBlWt6WLpo", "title": "མཎྜལ་ཆོ་ག", "icon": "🪷"}
                ],
                "repeated_segments": [{"segment_id": "<segment id>", "times": 3}],
                "return_jumps": [
                    {
                        "key": "praises_1",
                        "after_segment_id": "kYNR7EmC5apQWrkYl5fiO",
                        "to_segment_id": "BsajlElFFNFLoHcUjICwB",
                        "times": 3,
                        "label": {
                            "en": "↺ Return to start · 1st Praises to the 21 Tārās",
                            "bo": "",
                            "zh": "",
                        },
                    }
                ],
            }
        ],
    }


async def template_file(token: str, edition_id: str) -> Dict[str, Any]:
    """This edition's sections, ids filled in and titles empty, ready to fill
    and import. Rows already set keep their title and icon."""
    await run_in_threadpool(validate_cms_author_details, token=token)
    try:
        info = await library.fetch_edition_info(edition_id)
    except library.EditionNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Edition '{edition_id}' is not in the library",
        )
    sections = await library.fetch_toc_sections(edition_id)

    def stored() -> Optional[LiveEditionSettings]:
        with SessionLocal() as db:
            return get_edition_settings(db, edition_id)

    row = await run_in_threadpool(stored)
    current = {item["section_id"]: item for item in (row.short_titles if row else [])}
    return {
        "format": SETTINGS_FILE_FORMAT,
        "version": SETTINGS_FILE_VERSION,
        "editions": [
            {
                "edition_id": edition_id,
                "short_titles": [
                    {
                        "section_id": section.id,
                        "section_title": library.pick_title(section.title, info.language),
                        "title": current.get(section.id, {}).get("title", ""),
                        "icon": current.get(section.id, {}).get("icon", ""),
                    }
                    for section in sections
                ],
                "repeated_segments": list(row.repeated_segments) if row else [],
                "return_jumps": list(row.return_jumps) if row else [],
            }
        ],
    }


def export_file(token: str, event_id: UUID) -> Dict[str, Any]:
    """The event's room settings and every edition's settings. Edition settings
    are shared by all events, and there are few of them, so all are exported."""
    author = validate_cms_author_details(token=token)
    with SessionLocal() as db:
        require_event_editor(db, event_id, author)
        event = event_settings_dto(event_id, get_event_settings(db, event_id))
        rows = db.query(LiveEditionSettings).order_by(LiveEditionSettings.edition_id).all()
        return {
            "format": SETTINGS_FILE_FORMAT,
            "version": SETTINGS_FILE_VERSION,
            "event": {
                "followed_languages": event.followed_languages,
                "fallback_language": event.fallback_language,
                "record_play_times": event.record_play_times,
                "lead_max_ms": event.lead_max_ms,
            },
            "editions": [
                {
                    "edition_id": row.edition_id,
                    "short_titles": row.short_titles or [],
                    "repeated_segments": row.repeated_segments or [],
                    "return_jumps": row.return_jumps or [],
                }
                for row in rows
            ],
        }


def _path(location: tuple) -> str:
    """('editions', 0, 'return_jumps', 2, 'times') -> editions[0].return_jumps[2].times"""
    text = ""
    for part in location:
        if isinstance(part, int):
            text += f"[{part}]"
        else:
            text += f".{part}" if text else str(part)
    return text


def _parse(payload: Any) -> tuple[Optional[SettingsFile], List[ImportIssue]]:
    try:
        return SettingsFile.model_validate(payload), []
    except ValidationError as error:
        return None, [
            ImportIssue(path=_path(item["loc"]) or "(file)", message=item["msg"])
            for item in error.errors()
        ]


def _summary(file: SettingsFile) -> List[ImportEditionSummary]:
    def count(items):
        return None if items is None else len(items)

    return [
        ImportEditionSummary(
            edition_id=edition.edition_id,
            short_titles=count(edition.short_titles),
            repeated_segments=count(edition.repeated_segments),
            return_jumps=count(edition.return_jumps),
        )
        for edition in file.editions
    ]


async def import_file(
    token: str, payload: Any, event_id: Optional[UUID], dry_run: bool
) -> ImportReport:
    author = await run_in_threadpool(cms_writer, token)
    file, issues = _parse(payload)
    if file is None:
        return ImportReport(ok=False, applied=False, errors=issues)

    if file.event is not None:
        if event_id is None:
            issues.append(
                ImportIssue(path="event", message="import on an event's page to apply room settings")
            )
        else:

            def check_event() -> None:
                with SessionLocal() as db:
                    require_event_editor(db, event_id, author)

            await run_in_threadpool(check_event)

    for index, edition in enumerate(file.editions):
        issues.extend(
            await check_edition_lists(edition.edition_id, edition, path=f"editions[{index}].")
        )

    report = ImportReport(
        ok=not issues,
        applied=False,
        editions=_summary(file),
        event=file.event,
        errors=issues,
    )
    if issues or dry_run:
        return report

    def write() -> None:
        actor = actor_name(author)
        with SessionLocal() as db:
            for edition in file.editions:
                lists = edition_lists_to_store(edition)
                if lists:
                    upsert_edition_settings(db, edition.edition_id, lists, actor)
            if file.event is not None and event_id is not None:
                write_event_settings(db, event_id, file.event, actor)
            db.commit()

    await run_in_threadpool(write)
    return report.model_copy(update={"applied": True})


async def suggest_short_titles_service(token: str, edition_id: str) -> ShortTitleSuggestionsResponse:
    """A short title and icon for every section, from its title in the table of
    contents, in the edition's language. Nothing is saved."""
    await run_in_threadpool(cms_writer, token)
    try:
        info = await library.fetch_edition_info(edition_id)
    except library.EditionNotFound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Edition '{edition_id}' is not in the library",
        )
    sections = await library.fetch_toc_sections(edition_id)
    titles = {
        section.id: library.pick_title(section.title, info.language) or ""
        for section in sections
    }
    titles = {section_id: title for section_id, title in titles.items() if title.strip()}
    language = info.language or "en"
    suggested = await run_in_threadpool(
        suggest_short_titles, titles, language, SUGGESTED_TITLE_MAX_LENGTH
    )
    if suggested is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Short title suggestions are unavailable right now",
        )
    return ShortTitleSuggestionsResponse(
        edition_id=edition_id,
        language=info.language,
        suggestions=[
            ShortTitleSuggestion(
                section_id=section_id,
                section_title=titles.get(section_id),
                title=suggested[section_id][0],
                icon=suggested[section_id][1],
            )
            for section_id in titles
            if section_id in suggested
        ],
    )
