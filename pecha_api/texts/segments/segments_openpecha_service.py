import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from fastapi import HTTPException
from starlette import status

from openpecha_api.segments.openpecha_segment_service import (
    fetch_related_segments,
    fetch_segment_content,
    fetch_segment_details,
)
from openpecha_api.text.openpecha_text_service import fetch_text_by_id, search_by_content

from .segments_enum import SegmentType
from .segments_response_models import (
    ParentSegment,
    SegmentDTO,
    SegmentResponse,
    SegmentSearchRequest,
    SegmentRelatedText,
    SegmentResources,
    V2RelatedSegmentItem,
    V2SegmentCommentariesResponse,
    V2SegmentInfo,
    V2SegmentInfoResponse,
    V2SegmentResponse,
    V2SegmentRootTextResponse,
    V2SegmentTextDetail,
    V2SegmentTextGroup,
    V2SegmentTranslationsResponse,
)
from pecha_api.search.search_service import flatten_content_search_matches
from ..texts_openpecha_api import fetch_text_source_link
from ..texts_openpecha_service import _extract_title

logger = logging.getLogger(__name__)

TRANSLATION = "translation"
COMMENTARY = "commentary"
MAX_PAGINATION_SKIP = 10000
MAX_PAGINATION_LIMIT = 100
SEGMENT_SEARCH_LIMIT = 20


def _classify_text(text_payload: Dict[str, Any]) -> Optional[str]:
    if not text_payload:
        return None
    if text_payload.get("translation_of"):
        return TRANSLATION
    if text_payload.get("commentary_of"):
        return COMMENTARY
    return None


async def _fetch_text_safe(text_id: str) -> Optional[Dict[str, Any]]:
    try:
        return await fetch_text_by_id(text_id)
    except Exception:
        logger.exception("Failed to fetch text %s from upstream", text_id)
        return None


async def _fetch_segment_content_safe(segment_id: str) -> Optional[str]:
    try:
        return await fetch_segment_content(segment_id)
    except Exception:
        logger.exception("Failed to fetch segment content %s from upstream", segment_id)
        return None


async def _fetch_parent_segment(segment_id: str) -> ParentSegment:
    content = await _fetch_segment_content_safe(segment_id)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Segment with id '{segment_id}' not found",
        )
    return ParentSegment(segment_id=segment_id, content=content)


async def _get_related_segments_grouped_by_type(
    segment_id: str,
    related_type: str,
    skip: int,
    limit: int,
) -> Tuple[ParentSegment, List[V2SegmentTextGroup], bool]:

    try:
        parent_segment, related_page = await asyncio.gather(
            _fetch_parent_segment(segment_id),
            fetch_related_segments(segment_id=segment_id, limit=limit, offset=skip),
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch related segments from upstream service",
        )

    items: List[Dict[str, Any]] = related_page.get("items", []) or []
    has_more = bool(related_page.get("has_more", False))

    if not items:
        return parent_segment, [], has_more

    unique_text_ids: List[str] = []
    seen_text_ids = set()
    for item in items:
        text_id = item.get("text_id")
        if text_id and text_id not in seen_text_ids:
            seen_text_ids.add(text_id)
            unique_text_ids.append(text_id)

    text_payloads, source_links = await asyncio.gather(
        asyncio.gather(*[_fetch_text_safe(text_id) for text_id in unique_text_ids]),
        asyncio.gather(*[fetch_text_source_link(text_id) for text_id in unique_text_ids]),
    )
    text_by_id: Dict[str, Dict[str, Any]] = {
        text_id: payload
        for text_id, payload in zip(unique_text_ids, text_payloads)
        if payload is not None
    }
    source_by_id: Dict[str, Optional[str]] = dict(zip(unique_text_ids, source_links))

    filtered_items = [
        item
        for item in items
        if _classify_text(text_by_id.get(item.get("text_id", ""))) == related_type
    ]

    if not filtered_items:
        return parent_segment, [], has_more

    segment_contents = await asyncio.gather(
        *[_fetch_segment_content_safe(item["id"]) for item in filtered_items]
    )

    grouped: Dict[str, V2SegmentTextGroup] = {}
    group_order: List[str] = []
    for item, content in zip(filtered_items, segment_contents):
        text_id = item.get("text_id", "")
        if not text_id:
            continue
        if text_id not in grouped:
            text_payload = text_by_id.get(text_id, {})
            grouped[text_id] = V2SegmentTextGroup(
                text_id=text_id,
                title=_extract_title(text_payload.get("title", {})),
                language=text_payload.get("language"),
                source_link=source_by_id.get(text_id),
                license=text_payload.get("license"),
                segments=[],
            )
            group_order.append(text_id)
        grouped[text_id].segments.append(
            V2RelatedSegmentItem(id=item["id"], content=content)
        )

    return parent_segment, [grouped[text_id] for text_id in group_order], has_more


async def _fetch_matching_related_segments_by_text_id(
    segment_id: str,
    text_id: str,
    skip: int,
    limit: int,
) -> Tuple[List[Dict[str, Any]], bool]:
    safe_skip = max(0, min(skip, MAX_PAGINATION_SKIP))
    safe_limit = max(1, min(limit, MAX_PAGINATION_LIMIT))

    related_page = await fetch_related_segments(
        segment_id=segment_id,
        limit=safe_limit,
        offset=safe_skip,
        text_id=text_id,
    )
    items: List[Dict[str, Any]] = related_page.get("items", []) or []
    has_more = bool(related_page.get("has_more", False))
    return items, has_more


async def _resolve_root_text_id(segment_id: str) -> Optional[str]:
    """Callers don't know a segment's root text ahead of time, so resolve it from
    the segment's own text's translation_of/commentary_of pointer (mirrors the
    direction _classify_text uses for translations/commentaries, just inverted).

    Raises on upstream failure rather than swallowing it, so a dependency outage
    surfaces as a 502 instead of being reported as "this text has no root text".
    """
    segment_details = await fetch_segment_details(segment_id)
    text_payload = await fetch_text_by_id(segment_details.get("text_id"))
    if not text_payload:
        return None
    return text_payload.get("translation_of") or text_payload.get("commentary_of")


async def get_root_text_by_segment_id_from_openpecha(
    segment_id: str,
    text_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 10,
) -> V2SegmentRootTextResponse:
    if text_id is None:
        try:
            text_id = await _resolve_root_text_id(segment_id)
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to resolve root text from upstream service",
            )

    if text_id is None:
        parent_segment = await _fetch_parent_segment(segment_id)
        return V2SegmentRootTextResponse(
            parent_segment=parent_segment,
            root_text=[],
            skip=skip,
            limit=limit,
            has_more=False,
        )

    try:
        parent_segment, (filtered_items, has_more) = await asyncio.gather(
            _fetch_parent_segment(segment_id),
            _fetch_matching_related_segments_by_text_id(
                segment_id=segment_id,
                text_id=text_id,
                skip=skip,
                limit=limit,
            ),
        )
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch related segments from upstream service",
        )

    if not filtered_items:
        return V2SegmentRootTextResponse(
            parent_segment=parent_segment,
            root_text=[],
            skip=skip,
            limit=limit,
            has_more=has_more,
        )

    text_payload, *segment_contents = await asyncio.gather(
        _fetch_text_safe(text_id),
        *[_fetch_segment_content_safe(item["id"]) for item in filtered_items],
    )

    root_text_group = V2SegmentTextGroup(
        text_id=text_id,
        title=_extract_title(text_payload.get("title", {})) if text_payload else "",
        language=text_payload.get("language") if text_payload else None,
        segments=[
            V2RelatedSegmentItem(id=item["id"], content=content)
            for item, content in zip(filtered_items, segment_contents)
        ],
    )

    return V2SegmentRootTextResponse(
        parent_segment=parent_segment,
        root_text=[root_text_group],
        skip=skip,
        limit=limit,
        has_more=has_more,
    )

async def get_openpecha_segment_details_by_id(
    segment_id: str,
) -> V2SegmentResponse:
    content = await _fetch_segment_content_safe(segment_id)
    if content is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Segment with id '{segment_id}' not found",
        )

    segment_details=await fetch_segment_details(segment_id)
    text_payload = await _fetch_text_safe(segment_details.get("text_id"))
    if text_payload:
        text_detail = V2SegmentTextDetail(
            text_id=segment_details.get("text_id"),
            title=_extract_title(text_payload.get("title", {})),
            language=text_payload.get("language"),
        )
    else:
        text_detail = None

    return V2SegmentResponse(
        segment_id=segment_id,
        content=content,
        text=text_detail,
    )


async def get_translations_by_segment_id_from_openpecha(
    segment_id: str,
    skip: int = 0,
    limit: int = 10,
) -> V2SegmentTranslationsResponse:
    parent_segment, translations, has_more = await _get_related_segments_grouped_by_type(
        segment_id=segment_id,
        related_type=TRANSLATION,
        skip=skip,
        limit=limit,
    )
    return V2SegmentTranslationsResponse(
        parent_segment=parent_segment,
        translations=translations,
        skip=skip,
        limit=limit,
        has_more=has_more,
    )


async def get_commentaries_by_segment_id_from_openpecha(
    segment_id: str,
    skip: int = 0,
    limit: int = 10,
) -> V2SegmentCommentariesResponse:
    parent_segment, commentaries, has_more = await _get_related_segments_grouped_by_type(
        segment_id=segment_id,
        related_type=COMMENTARY,
        skip=skip,
        limit=limit,
    )
    return V2SegmentCommentariesResponse(
        parent_segment=parent_segment,
        commentaries=commentaries,
        skip=skip,
        limit=limit,
        has_more=has_more,
    )


async def get_segment_info_by_id_from_openpecha(
    segment_id: str,
) -> V2SegmentInfoResponse:
    try:
        segment_details = await fetch_segment_details(segment_id)
    except Exception:
        logger.exception("Failed to fetch segment details for %s", segment_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Segment with id '{segment_id}' not found",
        )

    text_id = segment_details.get("text_id")
    if not text_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Text ID not found for segment '{segment_id}'",
        )

    text_payload = await _fetch_text_safe(text_id)
    if not text_payload:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Text with id '{text_id}' not found",
        )

    translations_count = len(text_payload.get("translations", []))
    commentaries_count = len(text_payload.get("commentaries", []))

    root_text_count = 0
    if text_payload.get("commentary_of") or text_payload.get("translation_of"):
        root_text_count = 1

    segment_info = V2SegmentInfo(
        segment_id=segment_id,
        text_id=text_id,
        translations=translations_count,
        related_text=SegmentRelatedText(
            commentaries=commentaries_count,
            root_text=root_text_count,
        ),
        resources=SegmentResources(
            sheets=0,
        ),
    )

    return V2SegmentInfoResponse(segment_info=segment_info)


async def search_segments_by_content_service(
    segment_search_request: SegmentSearchRequest,
) -> SegmentResponse:
    """Segments whose content matches, from OpenPecha's content search. A
    failed search comes back empty, like a search with no hits."""
    try:
        results = await search_by_content(
            query=segment_search_request.content,
            limit=SEGMENT_SEARCH_LIMIT,
        )
    except Exception:
        logger.exception("OpenPecha segment content search failed")
        return SegmentResponse(segments=[])
    if not isinstance(results, list):
        logger.warning("Unexpected OpenPecha content search response type: %s", type(results).__name__)
        return SegmentResponse(segments=[])

    matches = flatten_content_search_matches(results)[:SEGMENT_SEARCH_LIMIT]
    return SegmentResponse(
        segments=[
            SegmentDTO(
                id=match["pecha_segment_id"],
                pecha_segment_id=match["pecha_segment_id"],
                text_id=match["text_id"],
                content=match["content"],
                type=SegmentType.SOURCE,
            )
            for match in matches
        ]
    )
