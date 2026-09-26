from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Query
from starlette import status

from pecha_api.plans.language_constants import language_query_description
from pecha_api.plans.public.plans_read_cache import (
    get_public_tag_detail_cached,
    get_public_tags_cached,
)
from pecha_api.plans.tags.tag_response_models import PublicTagsListResponse, PublicTagDetailDTO

public_tags_router = APIRouter(prefix="/public/tags", tags=["Public Tags"])


@public_tags_router.get("", status_code=status.HTTP_200_OK, response_model=PublicTagsListResponse)
async def get_tags(
    featured: Annotated[
        Optional[bool],
        Query(description="Filter by featured flag. Omit for all tags."),
    ] = None,
    search: Annotated[
        Optional[str],
        Query(description="Search by tag name."),
    ] = None,
    language: Annotated[
        Optional[str],
        Query(description=f"{language_query_description('Language code')}. Defaults to EN."),
    ] = "EN",
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
):
    return await get_public_tags_cached(
        featured=featured,
        search=search,
        language=language,
        skip=skip,
        limit=limit,
    )


@public_tags_router.get("/{tag_id}", status_code=status.HTTP_200_OK, response_model=PublicTagDetailDTO)
async def get_tag_detail(
    tag_id: UUID,
    language: Annotated[
        Optional[str],
        Query(description=f"{language_query_description('Language code')}. Defaults to EN."),
    ] = "EN",
):
    return await get_public_tag_detail_cached(
        tag_id=tag_id,
        language=language,
    )
