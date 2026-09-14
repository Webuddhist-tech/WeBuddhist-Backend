import os
import logging
from typing import Optional, List
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.uploads.S3_utils import generate_presigned_access_url, upload_file, delete_file
from pecha_api.config import get, get_int, DEFAULTS
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.plans.shared.permissions import require_super_admin
from .ambient_sound_repository import (
    get_ambient_sound_by_id,
    list_ambient_sounds,
    save_ambient_sound,
    update_ambient_sound,
    delete_ambient_sound,
    unset_other_defaults,
)
from .ambient_sound_response_models import AmbientSoundDTO, AmbientSoundsResponse
from .ambient_sound_model import AmbientSound
from .response_message import (
    NOT_FOUND,
    AMBIENT_SOUND_NOT_FOUND,
    INVALID_AUDIO_FILE_FORMAT,
    AUDIO_FILE_TOO_LARGE,
)

logger = logging.getLogger(__name__)


def generate_ambient_sound_presigned_url(s3_key: Optional[str]) -> Optional[str]:
    if not s3_key:
        return None
    try:
        bucket_name = get("AWS_BUCKET_NAME")
        return generate_presigned_access_url(bucket_name, s3_key)
    except Exception:
        logger.error(f"Failed to generate presigned URL for ambient sound: {s3_key}", exc_info=True)
        return None


def convert_ambient_sound_to_dto(ambient_sound: AmbientSound) -> AmbientSoundDTO:
    return AmbientSoundDTO(
        id=ambient_sound.id,
        name=ambient_sound.name,
        url=generate_ambient_sound_presigned_url(ambient_sound.s3_key),
        is_default=ambient_sound.is_default,
        display_order=ambient_sound.display_order
    )


def _validate_admin(token: str) -> None:
    author = validate_cms_author_details(token=token)
    require_super_admin(author)


def _validate_audio_file(file: UploadFile) -> None:
    file_extension = os.path.splitext(file.filename.lower())[1] if file.filename else ""
    allowed_extensions = DEFAULTS["ALLOWED_AUDIO_EXTENSIONS"]
    if file_extension not in allowed_extensions:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_AUDIO_FILE_FORMAT
        )
    if hasattr(file, "size") and file.size and file.size > get_int("MAX_AUDIO_FILE_SIZE"):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=AUDIO_FILE_TOO_LARGE
        )


def get_all_ambient_sounds_service() -> AmbientSoundsResponse:
    with SessionLocal() as db:
        ambient_sounds: List[AmbientSound] = list_ambient_sounds(db)
        return AmbientSoundsResponse(
            sounds=[convert_ambient_sound_to_dto(sound) for sound in ambient_sounds]
        )


def create_ambient_sound_service(
    token: str,
    name: str,
    display_order: int,
    is_default: bool,
    file: UploadFile
) -> AmbientSoundDTO:
    _validate_admin(token)
    _validate_audio_file(file)

    file_extension = os.path.splitext(file.filename.lower())[1] if file.filename else ""
    s3_key = f"audio/ambient_sounds/{uuid4()}{file_extension}"

    file.file.seek(0)
    upload_file(bucket_name=get("AWS_BUCKET_NAME"), s3_key=s3_key, file=file)

    with SessionLocal() as db:
        try:
            if is_default:
                unset_other_defaults(db)

            new_ambient_sound = AmbientSound(
                id=uuid4(),
                name=name,
                s3_key=s3_key,
                is_default=is_default,
                display_order=display_order
            )
            saved_ambient_sound = save_ambient_sound(db, new_ambient_sound)
        except Exception:
            delete_file(s3_key)
            raise
        return convert_ambient_sound_to_dto(saved_ambient_sound)


def update_ambient_sound_service(
    token: str,
    ambient_sound_id: UUID,
    name: Optional[str],
    display_order: Optional[int],
    is_default: Optional[bool],
    file: Optional[UploadFile]
) -> AmbientSoundDTO:
    _validate_admin(token)

    with SessionLocal() as db:
        ambient_sound = get_ambient_sound_by_id(db, ambient_sound_id)
        if not ambient_sound:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": AMBIENT_SOUND_NOT_FOUND}
            )

        old_s3_key = None
        new_s3_key = None
        if file is not None:
            _validate_audio_file(file)
            file_extension = os.path.splitext(file.filename.lower())[1] if file.filename else ""
            new_s3_key = f"audio/ambient_sounds/{uuid4()}{file_extension}"
            file.file.seek(0)
            upload_file(bucket_name=get("AWS_BUCKET_NAME"), s3_key=new_s3_key, file=file)
            old_s3_key = ambient_sound.s3_key
            ambient_sound.s3_key = new_s3_key

        if name is not None:
            ambient_sound.name = name
        if display_order is not None:
            ambient_sound.display_order = display_order
        if is_default is not None:
            if is_default:
                unset_other_defaults(db, exclude_id=ambient_sound.id)
            ambient_sound.is_default = is_default

        try:
            updated_ambient_sound = update_ambient_sound(db, ambient_sound)
        except Exception:
            if new_s3_key is not None:
                delete_file(new_s3_key)
            raise
        dto = convert_ambient_sound_to_dto(updated_ambient_sound)

    if old_s3_key:
        delete_file(old_s3_key)

    return dto


def delete_ambient_sound_service(token: str, ambient_sound_id: UUID) -> None:
    _validate_admin(token)

    with SessionLocal() as db:
        ambient_sound = get_ambient_sound_by_id(db, ambient_sound_id)
        if not ambient_sound:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": AMBIENT_SOUND_NOT_FOUND}
            )
        s3_key = ambient_sound.s3_key
        delete_ambient_sound(db, ambient_sound)

    delete_file(s3_key)
