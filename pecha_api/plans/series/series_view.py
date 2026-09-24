from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_invalidation_deps import invalidate_on_write
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette import status

from pecha_api.plans.language_constants import language_query_description
from pecha_api.plans.plans_enums import PlanStatus
from pecha_api.plans.series.series_response_models import CreateSeriesRequest, UpdateSeriesRequest, UpdateSeriesStatusRequest, SeriesDTO, SeriesListResponse, CloneSeriesPlansRequest, SeriesPartnerItemDTO, SeriesPartnerListResponse, AddSeriesPartnerRequest
from pecha_api.plans.series.series_service import create_new_series, update_existing_series, update_existing_series_status, update_existing_series_featured, get_cms_filtered_series, get_cms_series_detail, delete_existing_series, clone_series_plans_for_language, list_series_partners_for_cms, add_series_partner, remove_series_partner

oauth2_scheme = HTTPBearer()

cms_series_router = APIRouter(
    prefix="/cms/series",
    tags=["CMS Series"],
    # Every write on this router clears the namespaces it can affect.
    dependencies=[Depends(invalidate_on_write(
        CacheType.SERIES_LIST,
        CacheType.SERIES_FEATURED,
        CacheType.SERIES_DETAIL,
        CacheType.PLAN_LIST,
        CacheType.PLAN_DETAIL,
    ))],
)


@cms_series_router.post("", status_code=status.HTTP_201_CREATED, response_model=SeriesDTO,
)
async def create_series(authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
                        create_series_request: CreateSeriesRequest):
    return create_new_series(
        token=authentication_credential.credentials,
        create_series_request=create_series_request
    )


@cms_series_router.put(
    "/{series_id}",
    status_code=status.HTTP_200_OK,
    response_model=SeriesDTO,
)
async def update_series(
    series_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    update_series_request: UpdateSeriesRequest,
):
    return update_existing_series(
        token=authentication_credential.credentials,
        series_id=series_id,
        update_series_request=update_series_request,
    )


@cms_series_router.patch(
    "/{series_id}/status",
    status_code=status.HTTP_200_OK,
    response_model=SeriesDTO,
)
async def update_series_status(
    series_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    update_series_status_request: UpdateSeriesStatusRequest,
):
    return update_existing_series_status(
        token=authentication_credential.credentials,
        series_id=series_id,
        update_series_status_request=update_series_status_request,
    )


@cms_series_router.patch(
    "/{series_id}/featured",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def update_series_featured(
    series_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return update_existing_series_featured(
        token=authentication_credential.credentials,
        series_id=series_id,
    )


@cms_series_router.post(
    "/{series_id}/clone-plans",
    status_code=status.HTTP_200_OK,
    response_model=SeriesDTO,
)
async def clone_series_plans(
    series_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    clone_request: CloneSeriesPlansRequest,
):
    return clone_series_plans_for_language(
        token=authentication_credential.credentials,
        series_id=series_id,
        clone_request=clone_request,
    )


@cms_series_router.delete(
    "/{series_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_series(
    series_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return delete_existing_series(
        token=authentication_credential.credentials,
        series_id=series_id,
    )


@cms_series_router.get(
    "",
    status_code=status.HTTP_200_OK,
    response_model=SeriesListResponse,
)
async def get_cms_series_list(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    search: Annotated[
        Optional[str], Query(description="Search within serialized name JSON")
    ] = None,
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Filter by series metadata language", lowercase_example=True)),
    ] = None,
    status: Annotated[Optional[PlanStatus], Query()] = None,
    featured: Annotated[Optional[bool], Query()] = None,
    author_id: Annotated[
        Optional[UUID],
        Query(description="Filter by author ID (admins only; non-admins are scoped to their own series)"),
    ] = None,
    skip: Annotated[int, Query()] = 0,
    limit: Annotated[int, Query()] = 10,
):
    return get_cms_filtered_series(
        token=authentication_credential.credentials,
        search=search,
        skip=skip,
        limit=limit,
        language=language,
        plan_status=status,
        featured=featured,
        filter_author_id=author_id,
    )


@cms_series_router.get(
    "/{series_id}",
    status_code=status.HTTP_200_OK,
    response_model=SeriesDTO,
)
async def get_cms_series(
    series_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Filter plans by language", lowercase_example=True)),
    ] = None,
):
    return get_cms_series_detail(
        token=authentication_credential.credentials,
        series_id=series_id,
        language=language,
    )


@cms_series_router.get(
    "/{series_id}/partners",
    status_code=status.HTTP_200_OK,
    response_model=SeriesPartnerListResponse,
)
async def get_series_partners(
    series_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Language for partner group names", lowercase_example=True)),
    ] = None,
):
    return list_series_partners_for_cms(
        token=authentication_credential.credentials,
        series_id=series_id,
        language=language,
    )


@cms_series_router.post(
    "/{series_id}/partners",
    status_code=status.HTTP_201_CREATED,
    response_model=SeriesPartnerItemDTO,
)
async def create_series_partner(
    series_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    add_partner_request: AddSeriesPartnerRequest,
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Language for partner group name", lowercase_example=True)),
    ] = None,
):
    return add_series_partner(
        token=authentication_credential.credentials,
        series_id=series_id,
        add_request=add_partner_request,
        language=language,
    )


@cms_series_router.delete(
    "/{series_id}/partners/{group_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_series_partner(
    series_id: UUID,
    group_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return remove_series_partner(
        token=authentication_credential.credentials,
        series_id=series_id,
        group_id=group_id,
    )