from fastapi import APIRouter, Depends, Header, Query
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from typing import Optional, Annotated
from uuid import UUID
from starlette import status

from pecha_api.plans.language_constants import language_query_description
from pecha_api.plans.series.series_response_models import SeriesDTO, SeriesListResponse
from pecha_api.plans.series.series_cache_service import (
    get_filtered_series_cached,
    get_random_featured_series_cached,
    get_series_detail_cached,
)


public_series_router = APIRouter(prefix="/series", tags=["Public Series"])
optional_oauth2_scheme = HTTPBearer(auto_error=False)


def _token_from_credentials(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[str]:
    return credentials.credentials if credentials else None


@public_series_router.get(
    "", status_code=status.HTTP_200_OK, response_model=SeriesListResponse
)
async def get_series_list(
    search: Annotated[
        Optional[str], Query(description="Search within serialized name JSON")
    ] = None,
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Filter by series metadata language", lowercase_example=True)),
    ] = None,
    group_id: Annotated[
        Optional[UUID],
        Query(description="Filter by author group id"),
    ] = None,
    skip: Annotated[int, Query()] = 0,
    limit: Annotated[int, Query()] = 10,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(optional_oauth2_scheme)
    ] = None,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone (e.g. Asia/Shanghai). Restricted series are hidden for Chinese timezones."),
    ] = None,
):
    return await get_filtered_series_cached(
        search=search,
        skip=skip,
        limit=limit,
        language=language,
        group_id=group_id,
        token=_token_from_credentials(credentials),
        timezone_name=x_timezone,
    )


@public_series_router.get(
    "/featured",
    status_code=status.HTTP_200_OK,
    response_model=SeriesListResponse,
)
async def get_featured_series(
    language: Annotated[
        str,
        Query(
            description=(
                f"{language_query_description('Filter metadata by language', lowercase_example=True)}. "
                "Defaults to 'en'."
            ),
        ),
    ] = "en",
    limit: Annotated[int, Query()] = 10,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(optional_oauth2_scheme)
    ] = None,
):
    return await get_random_featured_series_cached(
        language=language,
        limit=limit,
        token=_token_from_credentials(credentials),
    )


@public_series_router.get(
    "/{series_id}", status_code=status.HTTP_200_OK, response_model=SeriesDTO
)
async def get_series(
    series_id: UUID,
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Filter plans by language", lowercase_example=True)),
    ] = None,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials], Depends(optional_oauth2_scheme)
    ] = None,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone (e.g. Asia/Shanghai). Restricted series are hidden for Chinese timezones."),
    ] = None,
):
    return await get_series_detail_cached(
        series_id=series_id,
        language=language,
        token=_token_from_credentials(credentials),
        timezone_name=x_timezone,
    )
