from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated, Optional
from uuid import UUID
from starlette import status

from .group_accumulator_service import (
    create_group_accumulator_cms_service,
    get_group_accumulators_cms_service,
    get_group_accumulator_cms_service,
    update_group_accumulator_cms_service,
    delete_group_accumulator_cms_service,
)
from .group_accumulator_response_models import (
    CreateGroupAccumulatorRequest,
    UpdateGroupAccumulatorRequest,
    GroupAccumulatorDTO,
    GroupAccumulatorsResponse,
    GroupAccumulatorDetailDTO,
)

group_accumulator_cms_router = APIRouter(prefix="/cms/groups", tags=["CMS - Group Accumulators"])
oauth2_scheme = HTTPBearer()


@group_accumulator_cms_router.post(
    "/{group_id}/accumulators",
    status_code=status.HTTP_201_CREATED,
    response_model=GroupAccumulatorDTO
)
async def create_group_accumulator(
    group_id: UUID,
    request: CreateGroupAccumulatorRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return create_group_accumulator_cms_service(
        token=credentials.credentials,
        group_id=group_id,
        request=request,
    )


@group_accumulator_cms_router.get(
    "/{group_id}/accumulators",
    response_model=GroupAccumulatorsResponse
)
async def get_group_accumulators(
    group_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    search: Optional[str] = Query(None, description="Filter by title"),
):
    return get_group_accumulators_cms_service(
        token=credentials.credentials,
        group_id=group_id,
        skip=skip,
        limit=limit,
        search=search,
    )


@group_accumulator_cms_router.get(
    "/{group_id}/accumulators/{group_accumulator_id}",
    response_model=GroupAccumulatorDetailDTO
)
async def get_single_group_accumulator(
    group_id: UUID,
    group_accumulator_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return get_group_accumulator_cms_service(
        token=credentials.credentials,
        group_id=group_id,
        group_accumulator_id=group_accumulator_id,
    )


@group_accumulator_cms_router.put(
    "/{group_id}/accumulators/{group_accumulator_id}",
    response_model=GroupAccumulatorDTO
)
async def update_group_accumulator(
    group_id: UUID,
    group_accumulator_id: UUID,
    request: UpdateGroupAccumulatorRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return update_group_accumulator_cms_service(
        token=credentials.credentials,
        group_id=group_id,
        group_accumulator_id=group_accumulator_id,
        request=request,
    )


@group_accumulator_cms_router.delete(
    "/{group_id}/accumulators/{group_accumulator_id}",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_group_accumulator(
    group_id: UUID,
    group_accumulator_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    delete_group_accumulator_cms_service(
        token=credentials.credentials,
        group_id=group_id,
        group_accumulator_id=group_accumulator_id,
    )
