from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated, Optional
from uuid import UUID
from starlette import status

from pecha_api.plans.language_constants import language_query_description
from .accumulator_cms_service import (
    list_preset_accumulators_cms_service,
    get_preset_accumulator_cms_service,
    create_preset_accumulator_cms_service,
    update_preset_accumulator_cms_service,
    delete_preset_accumulator_cms_service,
)
from .accumulator_response_models import (
    CreatePresetAccumulatorRequest,
    UpdatePresetAccumulatorRequest,
    CMSPublicAccumulatorDTO,
    CMSPublicAccumulatorsResponse,
)

accumulator_cms_router = APIRouter(
    prefix="/cms/accumulators/presets",
    tags=["CMS - Accumulator Presets"],
)
oauth2_scheme = HTTPBearer()


@accumulator_cms_router.get(
    "",
    response_model=CMSPublicAccumulatorsResponse,
    summary="List preset accumulators (CMS)",
)
async def list_preset_accumulators(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Language code for mantra content", lowercase_example=True)),
    ] = None,
    search: Annotated[
        Optional[str],
        Query(description="Filter by preset name/description or mantra text/title/pronunciation"),
    ] = None,
):
    return list_preset_accumulators_cms_service(
        token=credentials.credentials,
        skip=skip,
        limit=limit,
        search=search,
        language=language,
    )


@accumulator_cms_router.get(
    "/{preset_id}",
    response_model=CMSPublicAccumulatorDTO,
    summary="Get a preset accumulator (CMS)",
)
async def get_preset_accumulator(
    preset_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Language code for mantra content", lowercase_example=True)),
    ] = None,
):
    return get_preset_accumulator_cms_service(
        token=credentials.credentials,
        preset_id=preset_id,
        language=language,
    )


@accumulator_cms_router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=CMSPublicAccumulatorDTO,
    summary="Create a preset accumulator (CMS)",
)
async def create_preset_accumulator(
    request: CreatePresetAccumulatorRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return await create_preset_accumulator_cms_service(
        token=credentials.credentials,
        request=request,
    )


@accumulator_cms_router.put(
    "/{preset_id}",
    response_model=CMSPublicAccumulatorDTO,
    summary="Update a preset accumulator (CMS)",
)
async def update_preset_accumulator(
    preset_id: UUID,
    request: UpdatePresetAccumulatorRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return await update_preset_accumulator_cms_service(
        token=credentials.credentials,
        preset_id=preset_id,
        request=request,
    )


@accumulator_cms_router.delete(
    "/{preset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Soft-delete a preset accumulator (CMS)",
)
async def delete_preset_accumulator(
    preset_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    delete_preset_accumulator_cms_service(
        token=credentials.credentials,
        preset_id=preset_id,
    )
