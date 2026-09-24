import asyncio
import logging
from typing import Optional, Dict, Any, List, Tuple

from fastapi import HTTPException
from starlette import status

from pecha_api.texts.texts_response_models import (
    AvailableLanguage,
    LanguageResponse,
    TextDTO,
    TextVersion,
    TextVersionResponse,
    TextLanguageVersionsResponse,
    TitleSearchResult,
    V2TextDTO,
    V2TextsCategoryResponse,
)
from pecha_api.collections.collections_response_models import V2CollectionModel
from openpecha_api.text.openpecha_text_service import fetch_texts_by_category, fetch_text_by_id, search_by_content
from openpecha_api.collection.openpecha_collection_service import fetch_category_by_id
from openpecha_api.segments.openpecha_segment_service import fetch_segment_content
from pecha_api.texts.texts_enums import PaginationDirection
from pecha_api.texts.texts_openpecha_api import (
    fetch_critical_editions,
    fetch_edition_alignment_pairs,
    fetch_edition_text_id,
    fetch_editions_segmentation,
    fetch_edition_content,
    fetch_segmentation_segments,
    fetch_text_detail,
    fetch_text_source_link,
)
from pecha_api.texts.text_openpecha_response_models import (
    ContentDTO,
    EditionAlignmentPairModel,
    SectionDTO,
    SegmentationSegmentResponseModel,
    SegmentContentModel,
    SegmentContentResponse,
    SegmentSpans,
    SegmentDTO,
    SegmentTranslationDTO,
    TextDetailDTO,
    TextDetailResponse,
    TextDetailsRequest,
    TextDetailWithContentResponse,
)

logger = logging.getLogger(__name__)


def _extract_title(title_payload: Any, language: Optional[str] = None) -> str:
    if isinstance(title_payload, dict):
        if language and language in title_payload:
            return title_payload[language]
        for val in title_payload.values():
            if isinstance(val, str) and val.strip():
                return val
        return ""
    if isinstance(title_payload, str):
        return title_payload.strip()
    return ""


def _map_external_text_to_dto(item: Dict[str, Any], language: Optional[str] = None) -> V2TextDTO:
    title = _extract_title(item.get("title", {}), language)

    return V2TextDTO(
        id=item.get("id", ""),
        title=title,
        language=item.get("language") or "",
        license=item.get("license"),
    )


def map_external_text_to_dto(item: Dict[str, Any], language: Optional[str] = None) -> TextDTO:
    title = _extract_title(item.get("title", {}), language)
    date_value = item.get("date") or ""

    return TextDTO(
        id=item.get("id", ""),
        pecha_text_id=item.get("bdrc") or item.get("id", ""),
        title=title,
        language=item.get("language") or "",
        group_id=item.get("category_id") or "",
        type="root_text",
        summary="",
        is_published=True,
        created_date=date_value,
        updated_date=date_value,
        published_date=date_value,
        published_by="",
        categories=[item.get("category_id")] if item.get("category_id") else [],
        views=0,
        likes=[],
        source_link=item.get("source_link"),
        ranking=None,
        license=item.get("license"),
    )


async def _fetch_text_detail_with_source(text_id: str) -> Optional[Dict[str, Any]]:
    try:
        data = await fetch_text_by_id(text_id)
        if not data:
            return None
        source_link = await fetch_text_source_link(text_id)
        if source_link:
            data["source_link"] = source_link
        return data
    except Exception as e:
        logger.warning("Failed to fetch text %s: %s", text_id, e)
        return None


async def _get_texts_by_collection_id(
    collection_id: Optional[str],
    skip: int,
    limit: int,
    title: Optional[str] = None,
    language: Optional[str] = None,
) -> Tuple[List[V2TextDTO], bool]:
    try:
        page = await fetch_texts_by_category(
            category_id=collection_id,
            language=language,
            title=title,
            offset=skip,
            limit=limit,
        )
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch texts from upstream service",
        )

    items = page.get("items", [])
    has_more = bool(page.get("has_more", False))
    texts = [_map_external_text_to_dto(item, language) for item in items]

    return texts, has_more


async def get_texts_by_collection_from_openpecha(
    collection_id: Optional[str] = None,
    language: Optional[str] = None,
    title: Optional[str] = None,
    skip: int = 0,
    limit: int = 10,
) -> V2TextsCategoryResponse:
    texts, has_more = await _get_texts_by_collection_id(
        collection_id=collection_id,
        title=title,
        skip=skip,
        limit=limit,
        language=language,
    )

    collection: Optional[V2CollectionModel] = None
    if collection_id:
        category_title = ""
        try:
            category_data = await fetch_category_by_id(collection_id, language=language)
            if category_data:
                category_title = _extract_title(category_data.get("title", {}), language)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to fetch category title from upstream service",
            )

        collection = V2CollectionModel(
            id=collection_id,
            title=category_title,
        )

    return V2TextsCategoryResponse(
        collection=collection,
        texts=texts,
        skip=skip,
        limit=limit,
        has_more=has_more,
    )


async def get_titles_and_ids_by_query(
    title: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> List[TitleSearchResult]:
    """List texts (as their first critical edition), optionally filtered by title.
    An empty/missing title returns a default, unfiltered listing so callers can
    show a starting set of texts before the user has typed a search query."""
    texts, _ = await _get_texts_by_collection_id(
        collection_id=None,
        title=title or None,
        skip=offset,
        limit=limit,
    )
    if not texts:
        return []

    edition_ids = await asyncio.gather(*[_fetch_first_critical_edition_id(text.id) for text in texts])

    return [
        TitleSearchResult(id=edition_id, title=text.title)
        for text, edition_id in zip(texts, edition_ids)
        if edition_id
    ]


async def _fetch_first_critical_edition_id(text_id: str) -> Optional[str]:
    try:
        editions = await fetch_critical_editions(text_id=text_id)
    except Exception:
        logger.warning("Failed to fetch critical edition for text %s", text_id)
        return None
    return editions[0].id if editions else None


async def get_text_by_id_from_openpecha(text_id: str) -> V2TextDTO:
    try:
        data = await fetch_text_by_id(text_id)
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch text from upstream service",
        )

    if not data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Text with id '{text_id}' not found",
        )

    return _map_external_text_to_dto(data, data.get("language"))


async def _fetch_text_summary_by_edition_or_text_id(edition_or_text_id: str) -> Optional[V2TextDTO]:
    try:
        resolved_text_id = await _resolve_text_or_edition_id(edition_or_text_id)
        return await get_text_by_id_from_openpecha(text_id=resolved_text_id)
    except HTTPException as e:
        logger.warning(
            "Failed to fetch OpenPecha text details for %s: %s",
            edition_or_text_id, e.detail
        )
        return None


async def get_texts_by_edition_or_text_ids(text_ids: List[str]) -> Dict[str, V2TextDTO]:
    """Resolve collection-item ids (OpenPecha edition or text ids) to text details.

    Recitation collection items store OpenPecha edition ids as `text_id`, which
    are never synced into the local Mongo `Text` collection, so details must
    come straight from OpenPecha rather than a local lookup.
    """
    unique_ids = list(dict.fromkeys(text_ids))
    results = await asyncio.gather(
        *[_fetch_text_summary_by_edition_or_text_id(text_id) for text_id in unique_ids]
    )
    return {
        text_id: text
        for text_id, text in zip(unique_ids, results)
        if text is not None
    }


_ALL_SEGMENTS_PAGE_SIZE = 500


async def _fetch_all_segments(edition_id: str) -> List[SegmentSpans]:
    all_segments: List[SegmentSpans] = []
    offset = 0
    while True:
        page = await fetch_segmentation_segments(
            edition_id=edition_id, limit=_ALL_SEGMENTS_PAGE_SIZE, offset=offset
        )
        all_segments.extend(page.items)
        if not page.has_more:
            break
        offset += len(page.items)
    return all_segments


def _map_text_detail_dto(text_detail: TextDetailResponse) -> TextDetailDTO:
    title = _extract_title(text_detail.title, text_detail.language)
    date_value = text_detail.date or ""

    return TextDetailDTO(
        id=text_detail.id,
        pecha_text_id=text_detail.bdrc or text_detail.id,
        title=title,
        language=text_detail.language or "",
        group_id=text_detail.category_id or "",
        type="root_text",
        summary="",
        is_published=True,
        created_date=date_value,
        updated_date=date_value,
        published_date=date_value,
        published_by="",
        categories=[text_detail.category_id] if text_detail.category_id else [],
        views=0,
        likes=[],
        source_link=None,
        ranking=None,
        license=text_detail.license,
    )


def _trim_windowed_segments(
    edition_content: str,
    segments: List[SegmentSpans],
    start_position: int,
) -> List[SegmentDTO]:
    return [
        SegmentDTO(
            segment_id=segment.id,
            segment_number=start_position + i,
            content="".join(edition_content[line.start:line.end] for line in segment.lines),
        )
        for i, segment in enumerate(segments)
    ]


def _build_content_dto(
    edition_id: str,
    text_id: str,
    segmentation_id: str,
    segments: List[SegmentDTO],
) -> ContentDTO:
    return ContentDTO(
        id=edition_id,
        text_id=text_id,
        sections=[
            SectionDTO(
                id=segmentation_id,
                title="1",
                section_number=1,
                segments=segments,
            )
        ],
    )


_ALL_ALIGNMENT_PAIRS_PAGE_SIZE = 500


async def _fetch_all_alignment_pairs(source_edition_id: str, target_edition_id: str) -> List[EditionAlignmentPairModel]:
    """Fetch every direct segment alignment pair between two editions.

    A pair of editions with no direct alignment returns an empty list on the very first
    page (has_more=False), so this is cheap when there's nothing to find.
    """
    all_pairs: List[EditionAlignmentPairModel] = []
    offset = 0
    while True:
        page, has_more = await fetch_edition_alignment_pairs(
            source_edition_id=source_edition_id,
            target_edition_id=target_edition_id,
            limit=_ALL_ALIGNMENT_PAIRS_PAGE_SIZE,
            offset=offset,
        )
        all_pairs.extend(page)
        if not has_more:
            break
        offset += len(page)
    return all_pairs


async def _resolve_pivot_edition_id(
    edition_id: str,
    edition_text_id: str,
    edition_root_text_id: str,
    version_id: str,
    version_text_id: str,
    version_root_text_id: str,
) -> Optional[str]:
    """Two translations of the same root text are usually only aligned to that shared root
    edition, not to each other directly. Find an edition that both `edition_id` and
    `version_id` are (or are translations of), so their segments can be composed through it.
    """
    if edition_root_text_id != version_root_text_id:
        return None
    if edition_text_id == edition_root_text_id:
        return edition_id
    if version_text_id == version_root_text_id:
        return version_id
    critical_editions = await fetch_critical_editions(text_id=edition_root_text_id)
    return critical_editions[0].id if critical_editions else None


async def _map_segment_ids_to_pivot(
    segment_ids: List[str], edition_id: str, pivot_edition_id: str
) -> Dict[str, str]:
    """segment id in `edition_id` -> its aligned segment id in `pivot_edition_id`."""
    if edition_id == pivot_edition_id:
        return {segment_id: segment_id for segment_id in segment_ids}

    pairs = await _fetch_all_alignment_pairs(source_edition_id=edition_id, target_edition_id=pivot_edition_id)
    by_source_id = {pair.source_segment_id: pair.target_segment_id for pair in pairs}
    return {
        segment_id: by_source_id[segment_id]
        for segment_id in segment_ids
        if segment_id in by_source_id
    }


async def _map_pivot_ids_to_version_segments(
    pivot_segment_ids: List[str], pivot_edition_id: str, version_id: str
) -> Dict[str, List[str]]:
    """segment id in `pivot_edition_id` -> the aligned segment id(s) in `version_id`."""
    if version_id == pivot_edition_id:
        return {segment_id: [segment_id] for segment_id in pivot_segment_ids}

    pairs = await _fetch_all_alignment_pairs(source_edition_id=version_id, target_edition_id=pivot_edition_id)
    by_target_id: Dict[str, List[str]] = {}
    for pair in pairs:
        by_target_id.setdefault(pair.target_segment_id, []).append(pair.source_segment_id)
    return {
        segment_id: by_target_id[segment_id]
        for segment_id in pivot_segment_ids
        if segment_id in by_target_id
    }


async def _resolve_translation_segment_ids_via_pivot(
    segment_ids: List[str],
    edition_id: str,
    edition_text_id: str,
    edition_root_text_id: str,
    version_id: str,
    version_text_id: str,
    version_text_detail: TextDetailResponse,
) -> Dict[str, List[str]]:
    version_root_text_id = version_text_detail.translation_of or version_text_id

    pivot_edition_id = await _resolve_pivot_edition_id(
        edition_id=edition_id,
        edition_text_id=edition_text_id,
        edition_root_text_id=edition_root_text_id,
        version_id=version_id,
        version_text_id=version_text_id,
        version_root_text_id=version_root_text_id,
    )
    if pivot_edition_id is None:
        return {}

    edition_to_pivot = await _map_segment_ids_to_pivot(
        segment_ids=segment_ids, edition_id=edition_id, pivot_edition_id=pivot_edition_id,
    )
    if not edition_to_pivot:
        return {}

    pivot_to_version = await _map_pivot_ids_to_version_segments(
        pivot_segment_ids=list(edition_to_pivot.values()), pivot_edition_id=pivot_edition_id, version_id=version_id,
    )

    return {
        segment_id: pivot_to_version[pivot_id]
        for segment_id, pivot_id in edition_to_pivot.items()
        if pivot_id in pivot_to_version
    }


async def _resolve_translation_segment_ids(
    segment_ids: List[str],
    edition_id: str,
    edition_text_id: str,
    edition_text_detail: TextDetailResponse,
    version_id: str,
    version_text_id: str,
    version_text_detail: TextDetailResponse,
) -> Dict[str, List[str]]:
    """Map each of `segment_ids` (segments of `edition_id`) to the segment id(s) that hold its
    translation in `version_id`, trying the cheapest path first:
    1. a direct alignment from edition_id to version_id
    2. a direct alignment stored the other way round (version_id to edition_id)
    3. composing through a shared translation root (see _resolve_translation_segment_ids_via_pivot)
    """
    direct_pairs = await _fetch_all_alignment_pairs(source_edition_id=edition_id, target_edition_id=version_id)
    if direct_pairs:
        by_source_id: Dict[str, List[str]] = {}
        for pair in direct_pairs:
            by_source_id.setdefault(pair.source_segment_id, []).append(pair.target_segment_id)
        result = {segment_id: by_source_id[segment_id] for segment_id in segment_ids if segment_id in by_source_id}
        if result:
            return result

    reverse_pairs = await _fetch_all_alignment_pairs(source_edition_id=version_id, target_edition_id=edition_id)
    if reverse_pairs:
        by_target_id: Dict[str, List[str]] = {}
        for pair in reverse_pairs:
            by_target_id.setdefault(pair.target_segment_id, []).append(pair.source_segment_id)
        result = {segment_id: by_target_id[segment_id] for segment_id in segment_ids if segment_id in by_target_id}
        if result:
            return result

    edition_root_text_id = edition_text_detail.translation_of or edition_text_id
    return await _resolve_translation_segment_ids_via_pivot(
        segment_ids=segment_ids,
        edition_id=edition_id,
        edition_text_id=edition_text_id,
        edition_root_text_id=edition_root_text_id,
        version_id=version_id,
        version_text_id=version_text_id,
        version_text_detail=version_text_detail,
    )


async def _fetch_segment_content_safe(segment_id: str) -> Optional[str]:
    try:
        return await fetch_segment_content(segment_id=segment_id)
    except Exception:
        logger.warning("Failed to fetch content for segment '%s'", segment_id, exc_info=True)
        return None


async def _apply_translations(
    windowed_segments: List[SegmentDTO],
    edition_id: str,
    edition_text_id: str,
    edition_text_detail: TextDetailResponse,
    version_id: str,
) -> None:
    """Populate `translation` on each segment from the given translation edition (version_id),
    using the direct (or root-composed) segment alignment OpenPecha stores between editions.

    A missing alignment or a segment outside its coverage is skipped rather than failing the
    whole request; an invalid version_id itself surfaces as a 404.

    version_id accepts a text id as well as an edition id, since callers pick a version from
    the translation/version listings, which hand out text ids.
    """
    version_id, version_text_id = await _resolve_edition_id_for_details(version_id)
    version_text_detail = await fetch_text_detail(text_id=version_text_id)

    translation_ids_by_segment = await _resolve_translation_segment_ids(
        segment_ids=[segment.segment_id for segment in windowed_segments],
        edition_id=edition_id,
        edition_text_id=edition_text_id,
        edition_text_detail=edition_text_detail,
        version_id=version_id,
        version_text_id=version_text_id,
        version_text_detail=version_text_detail,
    )
    if not translation_ids_by_segment:
        logger.warning("No alignment found between edition '%s' and version '%s'", edition_id, version_id)
        return

    all_translation_ids = sorted({
        translation_id
        for translation_ids in translation_ids_by_segment.values()
        for translation_id in translation_ids
    })
    contents = await asyncio.gather(
        *[_fetch_segment_content_safe(segment_id=translation_id) for translation_id in all_translation_ids]
    )
    content_by_id = dict(zip(all_translation_ids, contents))
    version_language = version_text_detail.language or ""

    for segment in windowed_segments:
        translation_ids = translation_ids_by_segment.get(segment.segment_id)
        if not translation_ids:
            continue
        parts = [content_by_id[translation_id] for translation_id in translation_ids if content_by_id.get(translation_id)]
        if parts:
            segment.translation = SegmentTranslationDTO(
                text_id=version_id,
                language=version_language,
                content=" ".join(parts),
            )


async def _resolve_edition_id_for_details(text_or_edition_id: str) -> Tuple[str, str]:
    """Accepts either an edition id or a text id and returns (edition_id, text_id).

    Most callers only have a text id on hand (search results, text/version
    listings, related-segment groups), even though this endpoint's path was
    historically an edition id. Fall back to the text's first critical
    edition when the given id isn't already an edition.
    """
    try:
        text_id = await fetch_edition_text_id(edition_id=text_or_edition_id)
        return text_or_edition_id, text_id
    except HTTPException as exc:
        if exc.status_code != status.HTTP_404_NOT_FOUND:
            raise

    try:
        editions = await fetch_critical_editions(text_id=text_or_edition_id)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch critical editions from upstream service",
        ) from exc

    if not editions:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Edition with id '{text_or_edition_id}' not found",
        )
    return editions[0].id, text_or_edition_id


async def get_text_detail_by_id(
    edition_id: str,
    text_details_request: TextDetailsRequest,
) -> TextDetailWithContentResponse:
    edition_id, text_id = await _resolve_edition_id_for_details(edition_id)
    text_detail = await fetch_text_detail(text_id=text_id)

    segmentations = await fetch_editions_segmentation(edition_id=edition_id)
    if not segmentations:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No segmentation found for edition '{edition_id}'",
        )

    edition_content = await fetch_edition_content(edition_id=edition_id)
    all_segments = await _fetch_all_segments(edition_id=edition_id)

    text_detail_dto = _map_text_detail_dto(text_detail)
    total_segments = len(all_segments)
    size = text_details_request.size

    if total_segments == 0:
        return TextDetailWithContentResponse(
            text_detail=text_detail_dto,
            content=_build_content_dto(edition_id=edition_id, text_id=text_id, segmentation_id=segmentations[0].id, segments=[]),
            size=size,
            pagination_direction=text_details_request.direction.value,
            current_segment_position=0,
            total_segments=0,
        )

    if text_details_request.start is not None and text_details_request.end is not None:
        window_start = max(0, text_details_request.start - 1)
        window_end = max(window_start, min(text_details_request.end, total_segments))
        current_position = window_start + 1
    else:
        if text_details_request.segment_id:
            anchor_index = next(
                (i for i, segment in enumerate(all_segments) if segment.id == text_details_request.segment_id),
                None,
            )
            if anchor_index is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Segment with id '{text_details_request.segment_id}' not found",
                )
        else:
            anchor_index = 0

        if text_details_request.direction == PaginationDirection.NEXT:
            window_start = anchor_index
            window_end = min(anchor_index + size, total_segments)
        else:
            window_start = max(0, anchor_index - size + 1)
            window_end = anchor_index + 1
        current_position = anchor_index + 1

    windowed_segments = _trim_windowed_segments(
        edition_content=edition_content.content,
        segments=all_segments[window_start:window_end],
        start_position=window_start + 1,
    )

    if text_details_request.version_id:
        await _apply_translations(
            windowed_segments=windowed_segments,
            edition_id=edition_id,
            edition_text_id=text_id,
            edition_text_detail=text_detail,
            version_id=text_details_request.version_id,
        )

    return TextDetailWithContentResponse(
        text_detail=text_detail_dto,
        content=_build_content_dto(edition_id=edition_id, text_id=text_id, segmentation_id=segmentations[0].id, segments=windowed_segments),
        size=size,
        pagination_direction=text_details_request.direction.value,
        current_segment_position=current_position,
        total_segments=total_segments,
        has_more_up=window_start > 0,
        has_more_down=window_end < total_segments,
    )


def trim_segment_content(edition_content: str, segments: SegmentationSegmentResponseModel) -> SegmentContentResponse:
    result = []
    for i, segment in enumerate(segments.items):
        content = "".join(edition_content[line.start:line.end] for line in segment.lines)
        result.append(SegmentContentModel(id=segment.id, content=content, segment_number=i+1))
    return SegmentContentResponse(contents=result, has_more=segments.has_more, offset=segments.offset, limit=segments.limit)
async def fetch_translation_details(translation_ids: List[str]) -> List[Dict[str, Any]]:
    results = await asyncio.gather(
        *[_fetch_text_detail_with_source(translation_id) for translation_id in translation_ids]
    )
    return [item for item in results if item is not None]


def map_external_text_to_text_version(item: Dict[str, Any], language: Optional[str] = None) -> TextVersion:
    title = _extract_title(item.get("title", {}), language)
    date_value = item.get("date") or ""

    return TextVersion(
        id=item.get("id", ""),
        title=title,
        parent_id=item.get("translation_of") or item.get("commentary_of"),
        priority=None,
        language=item.get("language") or "",
        type="translation",
        group_id=item.get("category_id") or "",
        table_of_contents=[],
        is_published=True,
        created_date=date_value,
        updated_date=date_value,
        published_date=date_value,
        published_by="",
        source_link=item.get("source_link"),
        ranking=None,
        license=item.get("license"),
    )


def filter_versions_by_language(
    versions: List[TextVersion],
    language: Optional[str]
) -> List[TextVersion]:
    if not language:
        return versions
    return [v for v in versions if v.language == language]


def paginate_versions(
    versions: List[TextVersion],
    skip: int,
    limit: int
) -> List[TextVersion]:
    return versions[skip:skip + limit]


async def get_text_versions_from_openpecha(
    text_id: str,
    language: Optional[str] = None,
    skip: int = 0,
    limit: int = 10
) -> TextVersionResponse:

    try:
        text_data = await fetch_text_by_id(text_id)
    except Exception:
        logger.exception("Failed to fetch text from upstream service")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch text from upstream service",
        )

    if not text_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Text with id '{text_id}' not found",
        )

    root_text = map_external_text_to_dto(text_data, text_data.get("language"))

    commentary_of = text_data.get("commentary_of")
    translation_of = text_data.get("translation_of")
    translation_ids = text_data.get("translations", [])

    # A text's own `translations` list is authoritative for "what translations exist
    # of this text" — prefer it even when the text is itself a translation of something
    # else (translation_of only says what this text is a translation OF; it says
    # nothing about what's been translated FROM it). Only climb to the parent to find
    # sibling translations when this text has none of its own — e.g. a root text that
    # is itself a translation of an earlier source must still report its own
    # translations directly, not the translations of that earlier source.
    if not translation_ids and translation_of:
        return await _fetch_versions_from_parent(translation_of, root_text, language, skip, limit)

    # Only borrow versions from a related commentary when this text has no
    # translations of its own — a text's own translations must take priority,
    # otherwise this and get_text_languages_from_openpecha (which counts the
    # same list) can end up disagreeing about what a text's versions are.
    if not translation_ids and not commentary_of:
        commentary_ids = text_data.get("commentaries", [])
        if commentary_ids:
            return await _fetch_versions_from_related(commentary_ids[0], root_text, language, skip, limit)

    if not translation_ids:
        return TextVersionResponse(
            text=root_text,
            versions=[]
        )

    translation_details = await fetch_translation_details(translation_ids)

    versions = [
        map_external_text_to_text_version(item, item.get("language"))
        for item in translation_details
        if item.get("id") != root_text.id
    ]

    filtered_versions = filter_versions_by_language(versions, language)

    paginated_versions = paginate_versions(filtered_versions, skip, limit)

    return TextVersionResponse(
        text=root_text,
        versions=paginated_versions
    )


async def _resolve_text_or_edition_id(text_or_edition_id: str) -> str:
    """The language listing hands out edition ids, so accept either id here.

    OpenPecha 404s /v2/editions/{id} for a text id, which means the caller
    already gave us one.
    """
    try:
        return await fetch_edition_text_id(edition_id=text_or_edition_id)
    except HTTPException as exc:
        if exc.status_code == status.HTTP_404_NOT_FOUND:
            return text_or_edition_id
        raise


async def get_text_versions_by_edition_from_openpecha(
    edition_id: str,
    skip: int = 0,
    limit: int = 10
) -> TextVersionResponse:
    resolved_text_id = await _resolve_text_or_edition_id(edition_id)
    return await get_text_versions_from_openpecha(
        text_id=resolved_text_id,
        skip=skip,
        limit=limit
    )


async def _resolve_version_edition_ids(versions: List[TextVersion]) -> List[TextVersion]:
    """The reader app loads text details by edition id, so each version's id
    must be a critical edition id rather than the raw OpenPecha text id.
    """
    edition_ids = await asyncio.gather(
        *[_fetch_first_critical_edition_id(text_id=version.id) for version in versions]
    )
    return [
        version.model_copy(update={"id": edition_id or version.id})
        for version, edition_id in zip(versions, edition_ids)
    ]


async def get_text_versions_by_language_from_openpecha(
    edition_id: str,
    language: str,
    skip: int = 0,
    limit: int = 10
) -> TextLanguageVersionsResponse:
    resolved_text_id = await _resolve_text_or_edition_id(edition_id)
    versions_response = await get_text_versions_from_openpecha(
        text_id=resolved_text_id,
        language=language,
        skip=skip,
        limit=limit
    )
    available_versions = await _resolve_version_edition_ids(versions_response.versions or [])
    return TextLanguageVersionsResponse(
        text_id=edition_id,
        language=language,
        available_versions=available_versions
    )


async def get_text_languages_from_openpecha(edition_id: str) -> LanguageResponse:
    text_id = await fetch_edition_text_id(edition_id=edition_id)

    versions_response = await get_text_versions_from_openpecha(
        text_id=text_id,
        skip=0,
        limit=1000
    )

    language_counts: Dict[str, int] = {}
    for version in versions_response.versions:
        if version.language:
            language_counts[version.language] = language_counts.get(version.language, 0) + 1

    available_languages = [
        AvailableLanguage(
            language=lang,
            language_code=lang,
            version_count=count
        )
        for lang, count in language_counts.items()
    ]

    return LanguageResponse(
        text_id=edition_id,
        title=versions_response.text.title,
        available_languages=available_languages
    )


async def _fetch_versions_from_parent(
    parent_id: str,
    original_text: TextDTO,
    language: Optional[str],
    skip: int,
    limit: int
) -> TextVersionResponse:
    """Fetch versions from a parent text (translation_of)."""
    try:
        parent_data = await fetch_text_by_id(parent_id)
    except Exception:
        logger.warning(f"Failed to fetch parent text {parent_id}, returning empty versions")
        return TextVersionResponse(text=original_text, versions=[])

    if not parent_data:
        return TextVersionResponse(text=original_text, versions=[])

    translation_ids = parent_data.get("translations", [])

    if not translation_ids:
        return TextVersionResponse(text=original_text, versions=[])

    translation_details = await fetch_translation_details(translation_ids)

    versions = [
        map_external_text_to_text_version(item, item.get("language"))
        for item in translation_details
        if item.get("id") != original_text.id
    ]

    filtered_versions = filter_versions_by_language(versions, language)

    paginated_versions = paginate_versions(filtered_versions, skip, limit)

    return TextVersionResponse(
        text=original_text,
        versions=paginated_versions
    )


async def _fetch_versions_from_related(
    related_id: str,
    original_text: TextDTO,
    language: Optional[str],
    skip: int,
    limit: int
) -> TextVersionResponse:
    """Fetch versions from a related text (from translations or commentaries list)."""
    try:
        related_data = await fetch_text_by_id(related_id)
    except Exception:
        logger.warning(f"Failed to fetch related text {related_id}, returning empty versions")
        return TextVersionResponse(text=original_text, versions=[])

    if not related_data:
        return TextVersionResponse(text=original_text, versions=[])

    # Check if the related text has a translation_of pointing to a parent
    translation_of = related_data.get("translation_of")
    if translation_of:
        return await _fetch_versions_from_parent(translation_of, original_text, language, skip, limit)

    # Otherwise, get translations from the related text itself
    translation_ids = related_data.get("translations", [])

    if not translation_ids:
        return TextVersionResponse(text=original_text, versions=[])

    translation_details = await fetch_translation_details(translation_ids)

    versions = [
        map_external_text_to_text_version(item, item.get("language"))
        for item in translation_details
        if item.get("id") != original_text.id
    ]

    filtered_versions = filter_versions_by_language(versions, language)

    paginated_versions = paginate_versions(filtered_versions, skip, limit)

    return TextVersionResponse(
        text=original_text,
        versions=paginated_versions
    )


async def fetch_commentary_details(commentary_ids: List[str]) -> List[Dict[str, Any]]:
    results = await asyncio.gather(
        *[_fetch_text_detail_with_source(commentary_id) for commentary_id in commentary_ids]
    )
    return [item for item in results if item is not None]


async def get_text_commentaries_from_openpecha(
    text_id: str,
    skip: int = 0,
    limit: int = 10
) -> List[TextDTO]:

    try:
        text_data = await fetch_text_by_id(text_id)
    except Exception:
        logger.exception("Failed to fetch text from upstream service")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to fetch text from upstream service",
        )

    if not text_data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Text with id '{text_id}' not found",
        )

    commentary_of = text_data.get("commentary_of")
    translation_of = text_data.get("translation_of")

    # If commentary_of is not null, fetch commentaries from the parent text
    if commentary_of:
        return await _fetch_commentaries_from_parent(commentary_of, skip, limit)

    # If both commentary_of and translation_of are null, check translations and commentaries lists
    if not commentary_of and not translation_of:
        translation_ids = text_data.get("translations", [])
        commentary_ids = text_data.get("commentaries", [])

        # If there are translations or commentaries, fetch commentaries from the first available ID
        related_ids = translation_ids + commentary_ids
        if related_ids:
            return await _fetch_commentaries_from_related(related_ids[0], skip, limit)

    # Default: fetch commentaries directly from this text
    commentary_ids = text_data.get("commentaries", [])

    if not commentary_ids:
        return []

    commentary_details = await fetch_commentary_details(commentary_ids)

    commentaries = [
        map_external_text_to_dto(item, item.get("language"))
        for item in commentary_details
    ]

    paginated_commentaries = commentaries[skip:skip + limit]

    return paginated_commentaries


async def get_text_commentaries_by_edition_from_openpecha(
    edition_id: str,
    skip: int = 0,
    limit: int = 10
) -> List[TextDTO]:
    resolved_text_id = await _resolve_text_or_edition_id(edition_id)
    return await get_text_commentaries_from_openpecha(
        text_id=resolved_text_id,
        skip=skip,
        limit=limit
    )


async def _fetch_commentaries_from_parent(
    parent_id: str,
    skip: int,
    limit: int
) -> List[TextDTO]:
    """Fetch commentaries from a parent text (commentary_of)."""
    try:
        parent_data = await fetch_text_by_id(parent_id)
    except Exception:
        logger.warning(f"Failed to fetch parent text {parent_id}, returning empty commentaries")
        return []

    if not parent_data:
        return []

    commentary_ids = parent_data.get("commentaries", [])

    if not commentary_ids:
        return []

    commentary_details = await fetch_commentary_details(commentary_ids)

    commentaries = [
        map_external_text_to_dto(item, item.get("language"))
        for item in commentary_details
    ]

    return commentaries[skip:skip + limit]


async def _fetch_commentaries_from_related(
    related_id: str,
    skip: int,
    limit: int
) -> List[TextDTO]:
    """Fetch commentaries from a related text (from translations or commentaries list)."""
    try:
        related_data = await fetch_text_by_id(related_id)
    except Exception:
        logger.warning(f"Failed to fetch related text {related_id}, returning empty commentaries")
        return []

    if not related_data:
        return []

    # Check if the related text has a commentary_of pointing to a parent
    commentary_of = related_data.get("commentary_of")
    if commentary_of:
        return await _fetch_commentaries_from_parent(commentary_of, skip, limit)

    # Otherwise, get commentaries from the related text itself
    commentary_ids = related_data.get("commentaries", [])

    if not commentary_ids:
        return []

    commentary_details = await fetch_commentary_details(commentary_ids)

    commentaries = [
        map_external_text_to_dto(item, item.get("language"))
        for item in commentary_details
    ]

    return commentaries[skip:skip + limit]






async def search_text_content(
    query: str,
    search_type: Optional[str] = None,
    limit: Optional[int] = 10,
    text_id: Optional[str] = None,
    edition_id: Optional[str] = None,
) -> Dict[str, Any]:
    
 return await search_by_content(query, search_type, limit, text_id, edition_id)