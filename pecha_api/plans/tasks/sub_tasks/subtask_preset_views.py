from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette import status
from typing import Annotated
from uuid import UUID

from .subtask_preset_service import (
    create_or_update_preset_service,
    get_preset_service,
    delete_preset_service,
)
from .subtask_preset_cache_service import (
    get_preset_service_cached,
    invalidate_preset_cache,
)
from .subtask_preset_response_models import PresetRequest, PresetResponse


oauth2_scheme = HTTPBearer()
preset_router = APIRouter(
    prefix="/cms/sub-tasks",
    tags=["CMS SubTask Presets"]
)

public_preset_router = APIRouter(
    prefix="/sub-tasks",
    tags=["Public SubTask Presets"]
)


@preset_router.post(
    "/{subtask_id}/preset",
    status_code=status.HTTP_200_OK,
    summary="Create or update preset for subtask",
    description="Create or update the version preset for a subtask"
)
async def create_or_update_preset(
    subtask_id: UUID,
    preset_request: PresetRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> PresetResponse:
    result = await create_or_update_preset_service(
        token=authentication_credential.credentials,
        subtask_id=subtask_id,
        preset_request=preset_request
    )
    await invalidate_preset_cache(subtask_id=subtask_id)
    return result


@preset_router.get(
    "/{subtask_id}/preset",
    status_code=status.HTTP_200_OK,
    summary="Get preset for subtask",
    description="Get the version preset for a subtask"
)
async def get_preset(subtask_id: UUID) -> PresetResponse:
    return await get_preset_service_cached(subtask_id=subtask_id)


@preset_router.delete(
    "/{subtask_id}/preset",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete preset for subtask",
    description="Delete the version preset for a subtask"
)
async def delete_preset(
    subtask_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
) -> None:
    await delete_preset_service(
        token=authentication_credential.credentials,
        subtask_id=subtask_id
    )
    await invalidate_preset_cache(subtask_id=subtask_id)


@public_preset_router.get(
    "/{subtask_id}/preset",
    status_code=status.HTTP_200_OK,
    summary="Get preset for subtask (public)",
    description="Get the version preset for a subtask - public endpoint for app usage"
)
async def get_public_preset(subtask_id: UUID) -> PresetResponse:
    return await get_preset_service_cached(subtask_id=subtask_id)
