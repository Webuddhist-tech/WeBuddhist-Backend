from fastapi import APIRouter, Depends, Header, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated, Optional
from uuid import UUID
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api.plans.language_constants import language_query_description
from .accumulator_service import (
    get_all_accumulators_service,
    get_user_accumulators_service,
    create_accumulator_service,
    update_accumulator_service,
    delete_accumulator_service,
    get_accumulator_history_service,
    get_accumulator_detail_service,
    update_mala_image_service,
    get_accumulator_groups_service
)
from .accumulator_response_models import (
    AccumulatorsResponse,
    PublicAccumulatorsResponse,
    AccumulatorDTO,
    CreateAccumulatorRequest,
    UpdateAccumulatorRequest,
    UpdateMalaImageRequest,
    AccumulatorHistoryResponse,
    AccumulatorHistoryDTO,
    AccumulatorGroupsResponse
)
from ..users.users_service import validate_and_extract_user_details

accumulator_router = APIRouter(prefix="/accumulators", tags=["Accumulators"])
oauth2_scheme = HTTPBearer()


@accumulator_router.get(
    "/presets",
    response_model=PublicAccumulatorsResponse,
    summary="Get all public preset accumulators",
)
async def get_all_preset_accumulators(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Language code for mantra title, text, and pronunciation", lowercase_example=True)),
    ] = None,
    search: Annotated[
        Optional[str],
        Query(description="Filter presets by mantra text, title, or pronunciation (case-insensitive, any language)"),
    ] = None,
    show_recitations: Annotated[
        bool,
        Query(
            description=(
                "When false (default), exclude presets that have a text_id. "
                "When true, include text-linked (recitation) presets."
            ),
        ),
    ] = False,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone (e.g. Asia/Shanghai). Restricted accumulators are hidden for Chinese timezones."),
    ] = None,
):
    return get_all_accumulators_service(
        skip=skip,
        limit=limit,
        language=language,
        search=search,
        timezone_name=x_timezone,
        show_recitations=show_recitations,
    )


@accumulator_router.get("/user", response_model=AccumulatorsResponse)
async def get_user_accumulators(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
):
    current_user = validate_and_extract_user_details(token=credentials.credentials)
    return get_user_accumulators_service(
        user_id=current_user.id,
        skip=skip,
        limit=limit
    )


@accumulator_router.post("/user", status_code=status.HTTP_201_CREATED, response_model=AccumulatorDTO)
async def create_user_accumulator(
    request: CreateAccumulatorRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return create_accumulator_service(
        token=credentials.credentials,
        request=request
    )


@accumulator_router.put("/user/{accumulator_id}", response_model=AccumulatorDTO)
async def update_user_accumulator(
    accumulator_id: UUID,
    request: UpdateAccumulatorRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return await update_accumulator_service(
        token=credentials.credentials,
        accumulator_id=accumulator_id,
        request=request
    )


@accumulator_router.delete("/user/{accumulator_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_accumulator(
    accumulator_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    delete_accumulator_service(
        token=credentials.credentials,
        accumulator_id=accumulator_id
    )


@accumulator_router.put("/user/{accumulator_id}/mala-image", response_model=AccumulatorDTO)
async def update_accumulator_mala_image(
    accumulator_id: UUID,
    request: UpdateMalaImageRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return update_mala_image_service(
        token=credentials.credentials,
        accumulator_id=accumulator_id,
        request=request
    )


@accumulator_router.get("/user/history", response_model=AccumulatorHistoryResponse)
async def get_user_accumulator_history(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return")
):
    return get_accumulator_history_service(
        token=credentials.credentials,
        skip=skip,
        limit=limit
    )


@accumulator_router.get("/{accumulator_id}/groups", response_model=AccumulatorGroupsResponse)
async def get_accumulator_groups(
    accumulator_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    joined_only: bool = Query(
        False,
        description="When true, return only group accumulators the authenticated user has joined",
    ),
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Language code for the group name and event title", lowercase_example=True)),
    ] = None,
):
    """Get groups using this accumulator with the authenticated user's and the group's total count for each group."""
    return await run_in_threadpool(
        get_accumulator_groups_service,
        token=credentials.credentials,
        accumulator_id=accumulator_id,
        skip=skip,
        limit=limit,
        joined_only=joined_only,
        language=language,
    )


@accumulator_router.get("/{parent_id}", response_model=AccumulatorHistoryDTO)
async def get_accumulator_detail(
    parent_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return get_accumulator_detail_service(
        token=credentials.credentials,
        parent_id=parent_id
    )
