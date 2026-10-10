"""What the live control settings need from the library (OpenPecha) API.

Settings name sections and segments by their library ids, so an import or a
save is checked against the edition itself before anything is written."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from starlette import status

from pecha_api.external_clients import get_open_pecha_client
from pecha_api.texts.texts_openpecha_api import fetch_segmentation_segments

logger = logging.getLogger(__name__)

SEGMENT_PAGE_SIZE = 500
# A liturgy is a few hundred segments; this only stops a runaway scan.
MAX_SEGMENT_PAGES = 200


class EditionNotFound(Exception):
    pass


@dataclass(frozen=True)
class TocSection:
    id: str
    # Keyed by language code, as the library gives it.
    title: Dict[str, str]
    depth: int


@dataclass(frozen=True)
class EditionInfo:
    edition_id: str
    text_id: Optional[str]
    language: Optional[str]
    title: Optional[str]


async def _get(path: str, **params: Any):
    client = get_open_pecha_client()
    try:
        return await client.get_async_httpx_client().get(path, params=params or None)
    except Exception:
        logger.exception("Library request failed: %s", path)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The library could not be reached; try again",
        )


def _upstream_error(path: str, status_code: int) -> HTTPException:
    logger.error("Unexpected status %d from library: %s", status_code, path)
    return HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail="Unexpected response from the library",
    )


def _title_of(raw: object) -> Dict[str, str]:
    if isinstance(raw, dict):
        return {str(k).lower(): str(v) for k, v in raw.items() if isinstance(v, str) and v.strip()}
    if isinstance(raw, str) and raw.strip():
        return {"": raw}
    return {}


def pick_title(title: Dict[str, str], language: Optional[str]) -> Optional[str]:
    if not title:
        return None
    if language and title.get(language.lower()):
        return title[language.lower()]
    return next(iter(title.values()))


async def fetch_edition_info(edition_id: str) -> EditionInfo:
    path = f"/v2/editions/{edition_id}"
    response = await _get(path)
    if response.status_code == 404:
        raise EditionNotFound(edition_id)
    if response.status_code != 200:
        raise _upstream_error(path, response.status_code)
    text_id = (response.json() or {}).get("text_id")
    language = title = None
    if text_id:
        text_path = f"/v2/texts/{text_id}"
        text_response = await _get(text_path)
        if text_response.status_code == 200:
            data = text_response.json() or {}
            language = (data.get("language") or "").lower() or None
            title = pick_title(_title_of(data.get("title")), language)
    return EditionInfo(edition_id=edition_id, text_id=text_id, language=language, title=title)


def _flatten(sections: List[dict], depth: int, into: List[TocSection]) -> None:
    for section in sections or []:
        section_id = section.get("id")
        if section_id:
            into.append(TocSection(id=section_id, title=_title_of(section.get("title")), depth=depth))
        _flatten(section.get("subsections") or [], depth + 1, into)


async def fetch_toc_sections(edition_id: str) -> List[TocSection]:
    """Every section of the edition's table of contents, in reading order,
    subsections included. An edition with no table of contents has none."""
    path = f"/v2/editions/{edition_id}/table-of-contents"
    response = await _get(path)
    if response.status_code == 404:
        return []
    if response.status_code != 200:
        raise _upstream_error(path, response.status_code)
    sections: List[TocSection] = []
    for toc in response.json() or []:
        _flatten(toc.get("sections") or [], 0, sections)
    return sections


async def fetch_segment_order(edition_id: str) -> Dict[str, int]:
    """Each segment id of the edition and its place in reading order."""
    order: Dict[str, int] = {}
    offset = 0
    for _ in range(MAX_SEGMENT_PAGES):
        try:
            page = await fetch_segmentation_segments(
                edition_id=edition_id, limit=SEGMENT_PAGE_SIZE, offset=offset
            )
        except HTTPException as error:
            if error.status_code == status.HTTP_404_NOT_FOUND:
                return order
            raise
        for item in page.items:
            order.setdefault(item.id, len(order))
        if not page.has_more or not page.items:
            return order
        offset += len(page.items)
    return order
