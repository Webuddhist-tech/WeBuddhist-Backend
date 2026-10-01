import logging
from typing import Any, Dict, List, Optional

from openpecha_api.text.openpecha_text_service import search_by_content

from .search_response_models import (
    MultilingualSearchResponse,
    MultilingualSegmentMatch,
    MultilingualSourceResult,
)
from .search_service import (
    MAX_EXTERNAL_SEARCH_LIMIT,
    apply_pagination_to_sources,
    build_placeholder_text_index,
    create_empty_search_response,
    fetch_text_info,
    filter_live_edition_ids,
    flatten_content_search_matches,
)

logger = logging.getLogger(__name__)


async def _build_sources_from_content_search_matches(
    matches: List[Dict[str, Any]],
) -> List[MultilingualSourceResult]:
    # The response's `text.text_id` reports the edition_id, not the text_id, so
    # results are grouped by edition even though metadata is fetched by text_id.
    edition_to_matches: Dict[str, List[MultilingualSegmentMatch]] = {}
    edition_to_text_id: Dict[str, str] = {}
    edition_ids: List[str] = []

    for match in matches:
        edition_id = match.get("edition_id") or match["text_id"]
        text_id = match["text_id"]
        if not edition_id or not text_id:
            continue

        if edition_id not in edition_to_matches:
            edition_to_matches[edition_id] = []
            edition_to_text_id[edition_id] = text_id
            edition_ids.append(edition_id)

        edition_to_matches[edition_id].append(
            MultilingualSegmentMatch(
                segment_id=match["pecha_segment_id"],
                content=match["content"],
                relevance_score=match["relevance_score"],
                pecha_segment_id=match["pecha_segment_id"],
            )
        )

    if not edition_ids:
        return []

    # The content-search index still carries editions the graph has dropped;
    # they would 404 on /texts/{edition_id}/details the moment they're clicked.
    live_edition_ids = await filter_live_edition_ids(edition_ids)
    edition_ids = [edition_id for edition_id in edition_ids if edition_id in live_edition_ids]
    if not edition_ids:
        return []

    unique_text_ids = list(dict.fromkeys(edition_to_text_id[edition_id] for edition_id in edition_ids))
    text_info_map = await fetch_text_info(unique_text_ids)
    sources: List[MultilingualSourceResult] = []

    for edition_id in edition_ids:
        segment_matches = edition_to_matches[edition_id]
        segment_matches.sort(key=lambda item: item.relevance_score)

        text_info = text_info_map.get(edition_to_text_id[edition_id])
        text = (
            text_info.model_copy(update={"text_id": edition_id})
            if text_info
            else build_placeholder_text_index(edition_id)
        )

        sources.append(
            MultilingualSourceResult(
                text=text,
                segment_matches=segment_matches,
            )
        )

    return sources


async def get_multilingual_search_results(
    query: str,
    search_type: str = "similar",
    text_id: Optional[str] = None,
    edition_id: Optional[str] = None,
    skip: int = 0,
    limit: int = 10,
) -> MultilingualSearchResponse:
    try:
        # Ask upstream for its maximum window rather than a multiple of `limit`.
        # Roughly half the content-search index points at deleted editions, and
        # those orphans are ranked in among the live hits, so a narrow window can
        # come back entirely unopenable and leave the reader with nothing.
        external_limit = MAX_EXTERNAL_SEARCH_LIMIT

        # Upstream scopes by whichever id it is given: `text_id` covers every
        # edition of a work, `edition_id` narrows to one. They are distinct ids,
        # so a text_id passed as edition_id matches nothing and the caller gets
        # an empty page for a word that is plainly in the text.
        external_data = await search_by_content(
            query=query,
            search_type=search_type,
            limit=external_limit,
            text_id=text_id,
            edition_id=edition_id,
        )

        if not isinstance(external_data, list):
            logger.warning(
                "Unexpected OpenPecha content search response type: %s",
                type(external_data).__name__,
            )
            return create_empty_search_response(query, search_type, skip, limit)

        matches = flatten_content_search_matches(external_data)
        if not matches:
            logger.info("No matches returned from OpenPecha content search")
            return create_empty_search_response(query, search_type, skip, limit)

        sources = await _build_sources_from_content_search_matches(matches)

        if not sources:
            return create_empty_search_response(query, search_type, skip, limit)

        paginated_sources = apply_pagination_to_sources(sources, skip, limit)

        return MultilingualSearchResponse(
            query=query,
            search_type=search_type,
            sources=paginated_sources,
            skip=skip,
            limit=limit,
            # Counts the openable matches only, so `total` agrees with what
            # paging through the sources actually yields.
            total=sum(len(source.segment_matches) for source in sources),
        )

    except Exception:
        logger.exception("Error in multilingual search")
        raise
