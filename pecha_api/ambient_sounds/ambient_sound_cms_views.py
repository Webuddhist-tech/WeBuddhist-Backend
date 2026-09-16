from fastapi import APIRouter, Depends, Form, File, UploadFile
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated, Optional
from uuid import UUID
from starlette import status

from .ambient_sound_service import (
    create_ambient_sound_service,
    update_ambient_sound_service,
    delete_ambient_sound_service,
)
from .ambient_sound_response_models import AmbientSoundDTO

ambient_sound_cms_router = APIRouter(prefix="/ambient-sounds/cms", tags=["CMS - Ambient Sounds"])
oauth2_scheme = HTTPBearer()


@ambient_sound_cms_router.post("", status_code=status.HTTP_201_CREATED, response_model=AmbientSoundDTO)
async def create_ambient_sound(
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    name: str = Form(...),
    display_order: int = Form(0),
    is_default: bool = Form(False),
    file: UploadFile = File(...),
    image_file: Optional[UploadFile] = File(None)
):
    return create_ambient_sound_service(
        token=credentials.credentials,
        name=name,
        display_order=display_order,
        is_default=is_default,
        file=file,
        image_file=image_file
    )


@ambient_sound_cms_router.put("/{ambient_sound_id}", response_model=AmbientSoundDTO)
async def update_ambient_sound(
    ambient_sound_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    name: Optional[str] = Form(None),
    display_order: Optional[int] = Form(None),
    is_default: Optional[bool] = Form(None),
    file: Optional[UploadFile] = File(None),
    image_file: Optional[UploadFile] = File(None)
):
    return update_ambient_sound_service(
        token=credentials.credentials,
        ambient_sound_id=ambient_sound_id,
        name=name,
        display_order=display_order,
        is_default=is_default,
        file=file,
        image_file=image_file
    )


@ambient_sound_cms_router.delete("/{ambient_sound_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_ambient_sound(
    ambient_sound_id: UUID,
    credentials: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    delete_ambient_sound_service(
        token=credentials.credentials,
        ambient_sound_id=ambient_sound_id
    )
