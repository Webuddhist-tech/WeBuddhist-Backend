from typing import Optional

from fastapi import APIRouter, Query
from starlette import status

from .search_enums import SearchType, MultilingualSearchType
from .search_openpecha_service import get_multilingual_search_results
from .search_service import (
    get_search_results,
    get_url_link as get_url_link_service,
)
from .search_response_models import (
    SearchResponse,
    MultilingualSearchResponse,
    SegmentLinkResponse,
)

search_router = APIRouter(
    prefix="/search",
    tags=["Search"],
)


@search_router.get("", status_code=status.HTTP_200_OK)
async def search(
    query: str = Query(default=None, description="Search query"),
    search_type: SearchType = Query(default=None, description="Search type (SOURCE / SHEET)"),
    text_id: Optional[str] = Query(default=None, description="Text ID where the search is to be performed"),
    skip: int = Query(default=0),
    limit: int = Query(default=10),
) -> SearchResponse:
    return await get_search_results(
        query=query,
        search_type=search_type,
        text_id=text_id,
        skip=skip,
        limit=limit,
    )


@search_router.get("/multilingual", status_code=status.HTTP_200_OK)
async def multilingual_search(
    query: str = Query(...),
    search_type: MultilingualSearchType = Query(default=MultilingualSearchType.SIMILAR),
    text_id: Optional[str] = Query(default=None, description="Restrict the search to every edition of this text"),
    edition_id: Optional[str] = Query(default=None, description="Restrict the search to a single edition"),
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=10, ge=1, le=100),
) -> MultilingualSearchResponse:
    return await get_multilingual_search_results(
        query=query,
        search_type=search_type.value,
        text_id=text_id,
        edition_id=edition_id,
        skip=skip,
        limit=limit,
    )


@search_router.get("/chat/{pecha_segment_id}", status_code=status.HTTP_200_OK)
async def get_url_link(pecha_segment_id: str) -> SegmentLinkResponse:
    return await get_url_link_service(pecha_segment_id)
