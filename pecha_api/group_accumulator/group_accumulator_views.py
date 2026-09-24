from fastapi import APIRouter, Depends, Query, Response, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated, Optional
from uuid import UUID
from starlette import status

from pecha_api.plans.language_constants import language_query_description
from .group_accumulator_service import (
    get_group_accumulator_service,
    get_group_accumulators_service,
    submit_group_count_service,
    get_group_accumulator_history_service,
    delete_group_accumulator_user_service,
    join_group_accumulator_service,
    get_group_accumulator_members_service,
    get_group_accumulator_user_sessions_service,
)
from .group_accumulator_response_models import (
    SubmitGroupCountRequest,
    GroupAccumulatorDetailDTO,
    GroupAccumulatorsResponse,
    GroupAccumulatorHistoryResponse,
    GroupAccumulatorHistoryItemDTO,
    GroupAccumulatorMembersResponse,
    GroupAccumulatorUserSessionsResponse,
    GroupAccumulatorMemberSortBy,
)

group_accumulator_router = APIRouter(prefix="/group-accumulators", tags=["Group Accumulators"])
oauth2_scheme = HTTPBearer()
optional_oauth2_scheme = HTTPBearer(auto_error=False)


@group_accumulator_router.get(
    "/{group_id}/accumulators",
    response_model=GroupAccumulatorsResponse
)
async def get_group_accumulators(
    group_id: UUID,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(optional_oauth2_scheme),
    ] = None,
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Language code for the About description")),
    ] = None,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone (e.g. Asia/Shanghai). Restricted group accumulators are hidden for Chinese timezones."),
    ] = None,
):
    token = credentials.credentials if credentials else None
    return get_group_accumulators_service(
        group_id=group_id,
        skip=skip,
        limit=limit,
        token=token,
        timezone_name=x_timezone,
        language=language,
    )


@group_accumulator_router.get("/{group_accumulator_id}", response_model=GroupAccumulatorDetailDTO)
async def get_group_accumulator(
    group_accumulator_id: UUID,
    credentials: Annotated[
        Optional[HTTPAuthorizationCredentials],
        Depends(optional_oauth2_scheme),
    ] = None,
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Language code for the About description")),
    ] = None,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone for today counts (e.g. Asia/Kathmandu). Defaults to UTC."),
    ] = None,
):
    """Get group accumulator details including lifetime and today totals."""
    token = credentials.credentials if credentials else None
    return get_group_accumulator_service(
        group_accumulator_id=group_accumulator_id,
        timezone_name=x_timezone,
        token=token,
        language=language,
    )


@group_accumulator_router.post(
    "/{group_accumulator_id}",
    response_model=GroupAccumulatorHistoryItemDTO,
    responses={
        201: {"description": "New history entry created"},
        200: {"description": "No change (delta <= 0)"},
    }
)
async def submit_group_count(
    group_accumulator_id: UUID,
    request: SubmitGroupCountRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    response: Response,
):
    result, is_created = submit_group_count_service(
        token=credentials.credentials,
        group_accumulator_id=group_accumulator_id,
        request=request,
    )
    response.status_code = status.HTTP_201_CREATED if is_created else status.HTTP_200_OK
    return result


@group_accumulator_router.get(
    "/{group_accumulator_id}/history",
    response_model=GroupAccumulatorHistoryResponse
)
async def get_group_accumulator_history(
    group_accumulator_id: UUID,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    today_only: bool = Query(
        False,
        description="When true, return only history entries from today in the request timezone",
    ),
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone for today filter (e.g. Asia/Kathmandu). Defaults to UTC."),
    ] = None,
):
    return get_group_accumulator_history_service(
        group_accumulator_id=group_accumulator_id,
        skip=skip,
        limit=limit,
        today_only=today_only,
        timezone_name=x_timezone,
    )


@group_accumulator_router.post(
    "/{group_accumulator_id}/join",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def join_group_accumulator(
    group_accumulator_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Join a group accumulator. Also joins the parent group automatically."""
    join_group_accumulator_service(
        token=credentials.credentials,
        group_accumulator_id=group_accumulator_id,
    )
    return None


@group_accumulator_router.get(
    "/{group_accumulator_id}/members",
    response_model=GroupAccumulatorMembersResponse,
)
async def get_group_accumulator_members(
    group_accumulator_id: UUID,
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    sort_by: GroupAccumulatorMemberSortBy = Query(
        GroupAccumulatorMemberSortBy.TOTAL,
        description="Sort members by lifetime total (`total`) or today's count (`today`), highest first",
    ),
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone for today counts (e.g. Asia/Kathmandu). Defaults to UTC."),
    ] = None,
):
    """List users who joined this group accumulator, sorted by contribution count."""
    return get_group_accumulator_members_service(
        group_accumulator_id=group_accumulator_id,
        skip=skip,
        limit=limit,
        timezone_name=x_timezone,
        sort_by=sort_by,
    )


@group_accumulator_router.get(
    "/{group_accumulator_id}/user-sessions",
    response_model=GroupAccumulatorUserSessionsResponse,
)
async def get_group_accumulator_user_sessions(
    group_accumulator_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
):
    """List the authenticated user's participation sessions for a group accumulator."""
    return get_group_accumulator_user_sessions_service(
        token=credentials.credentials,
        group_accumulator_id=group_accumulator_id,
        skip=skip,
        limit=limit,
    )


@group_accumulator_router.delete(
    "/{group_accumulator_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_group_accumulator(
    group_accumulator_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    """Reset the user's active participation in a group accumulator (counts go to zero)."""
    delete_group_accumulator_user_service(
        token=credentials.credentials,
        group_accumulator_id=group_accumulator_id,
    )
    return None
