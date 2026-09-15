from fastapi import APIRouter, Depends, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated, Optional
from uuid import UUID
from starlette import status

from .timer_service import (
    get_all_timers_service,
    get_user_timers_service,
    create_timer_service,
    update_timer_service,
    delete_timer_service,
    restore_timer_service,
    record_timer_stop_service,
    get_timer_history_service
)
from .timer_audio_service import (
    create_timer_audio_service,
    delete_timer_audio_service,
    list_timer_audios_service,
    update_timer_audio_service,
)
from .timer_response_models import (
    TimersResponse,
    TimerDTO,
    CreateTimerRequest,
    UpdateTimerRequest,
    RecordTimerStopRequest,
    RecordTimerStopResponse,
    TimerHistoryResponse,
    TimerAudioDTO,
    TimerAudiosResponse,
    CreateTimerAudioRequest,
    UpdateTimerAudioRequest
)
from ..users.users_service import validate_and_extract_user_details

timer_router = APIRouter(prefix="/timers", tags=["Timers"])
oauth2_scheme = HTTPBearer()


@timer_router.get("", response_model=TimersResponse)
async def get_all_timers(
    group_id: Optional[UUID] = Query(None, description="Group ID to filter timers"),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
):
    return get_all_timers_service(group_id=group_id, skip=skip, limit=limit)


@timer_router.get("/user", response_model=TimersResponse)
async def get_user_timers(
    group_id: Optional[UUID] = Query(None, description="Optional group filter. Omit to return every timer the caller created."),
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return"),
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)] = None
):
    current_user = validate_and_extract_user_details(token=credentials.credentials)
    return get_user_timers_service(
        user_id=current_user.id,
        group_id=group_id,
        skip=skip,
        limit=limit
    )


@timer_router.post("/user", status_code=status.HTTP_201_CREATED, response_model=TimerDTO)
async def create_user_timer(
    request: CreateTimerRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return create_timer_service(
        token=credentials.credentials,
        request=request
    )


@timer_router.put("/user/{timer_id}", response_model=TimerDTO)
async def update_user_timer(
    timer_id: UUID,
    request: UpdateTimerRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return update_timer_service(
        token=credentials.credentials,
        timer_id=timer_id,
        request=request
    )


@timer_router.delete("/user/{timer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_timer(
    timer_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    delete_timer_service(
        token=credentials.credentials,
        timer_id=timer_id
    )


@timer_router.post("/user/{timer_id}/restore", response_model=TimerDTO)
async def restore_user_timer(
    timer_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return restore_timer_service(
        token=credentials.credentials,
        timer_id=timer_id
    )


@timer_router.post("/user/timer_stop", status_code=status.HTTP_201_CREATED, response_model=RecordTimerStopResponse)
async def record_timer_stop(
    request: RecordTimerStopRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return record_timer_stop_service(
        token=credentials.credentials,
        request=request
    )


@timer_router.get("/user/timer_history", response_model=TimerHistoryResponse)
async def get_user_timer_history(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return")
):
    return get_timer_history_service(
        token=credentials.credentials,
        skip=skip,
        limit=limit
    )


@timer_router.get("/audios", response_model=TimerAudiosResponse)
async def list_timer_audios(
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return")
):
    """Every uploaded audio with its cover image, so a user can pick one for
    their own timer. Shared: the list is not filtered by owner."""
    return list_timer_audios_service(skip=skip, limit=limit)


@timer_router.post("/audios", status_code=status.HTTP_201_CREATED, response_model=TimerAudioDTO)
async def create_timer_audio(
    request: CreateTimerAudioRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return create_timer_audio_service(
        token=credentials.credentials,
        request=request
    )


@timer_router.put("/audios/{timer_audio_id}", response_model=TimerAudioDTO)
async def update_timer_audio(
    timer_audio_id: UUID,
    request: UpdateTimerAudioRequest,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    """Only the uploader may change an audio."""
    return update_timer_audio_service(
        token=credentials.credentials,
        timer_audio_id=timer_audio_id,
        request=request
    )


@timer_router.delete("/audios/{timer_audio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_timer_audio(
    timer_audio_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    """Only the uploader may delete. Timers using it keep working; their
    timer_audio_id is set to NULL."""
    delete_timer_audio_service(
        token=credentials.credentials,
        timer_audio_id=timer_audio_id
    )
