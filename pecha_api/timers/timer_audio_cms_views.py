from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated, Optional
from uuid import UUID
from starlette.concurrency import run_in_threadpool
from starlette import status

from .timer_audio_service import (
    create_preset_timer_audio_service,
    delete_preset_timer_audio_service,
    list_preset_timer_audios_service,
    update_preset_timer_audio_service,
)
from .timer_response_models import TimerAudioDTO, TimerAudiosResponse

timer_audio_cms_router = APIRouter(prefix="/timers/audios/cms", tags=["CMS - Timer Audios"])
oauth2_scheme = HTTPBearer()


@timer_audio_cms_router.get("", response_model=TimerAudiosResponse)
async def list_preset_timer_audios(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    skip: int = Query(0, ge=0, description="Number of records to skip"),
    limit: int = Query(20, ge=1, le=100, description="Maximum number of records to return")
):
    """The preset catalogue only. Users' own uploads never appear here."""
    return await run_in_threadpool(
        list_preset_timer_audios_service,
        token=credentials.credentials,
        skip=skip,
        limit=limit
    )


@timer_audio_cms_router.post("", status_code=status.HTTP_201_CREATED, response_model=TimerAudioDTO)
async def create_preset_timer_audio(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    name: str = Form(...),
    audio_file: UploadFile = File(...),
    image_file: Optional[UploadFile] = File(None)
):
    """Publish a timer audio preset, visible to every user. Image optional."""
    return await run_in_threadpool(
        create_preset_timer_audio_service,
        token=credentials.credentials,
        name=name,
        audio_file=audio_file,
        image_file=image_file
    )


@timer_audio_cms_router.put("/{timer_audio_id}", response_model=TimerAudioDTO)
async def update_preset_timer_audio(
    timer_audio_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    name: Optional[str] = Form(None),
    audio_file: Optional[UploadFile] = File(None),
    image_file: Optional[UploadFile] = File(None)
):
    return await run_in_threadpool(
        update_preset_timer_audio_service,
        token=credentials.credentials,
        timer_audio_id=timer_audio_id,
        name=name,
        audio_file=audio_file,
        image_file=image_file
    )


@timer_audio_cms_router.delete("/{timer_audio_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset_timer_audio(
    timer_audio_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    await run_in_threadpool(
        delete_preset_timer_audio_service,
        token=credentials.credentials,
        timer_audio_id=timer_audio_id
    )
