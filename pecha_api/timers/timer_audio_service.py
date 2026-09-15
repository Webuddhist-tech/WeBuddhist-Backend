import logging
import os
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from starlette import status

from ..config import get, get_int, DEFAULTS
from ..db.database import SessionLocal
from ..uploads.S3_utils import delete_file, generate_presigned_access_url, upload_file
from ..users.users_service import validate_and_extract_user_details
from ..plans.authors.plan_authors_service import validate_cms_author_details
from ..plans.shared.permissions import require_super_admin
from .response_message import (
    AUDIO_FILE_TOO_LARGE,
    FORBIDDEN,
    INVALID_AUDIO_FILE_FORMAT,
    NOT_FOUND,
    TIMER_AUDIO_DELETE_NOT_ALLOWED,
    TIMER_AUDIO_NOT_FOUND,
    TIMER_AUDIO_UPDATE_NOT_ALLOWED,
)
from .timer_audio_enums import TimerAudioType
from .timer_audio_model import TimerAudio
from .timer_audio_repository import (
    count_preset_timer_audios,
    count_visible_timer_audios,
    delete_timer_audio,
    get_timer_audio_by_id,
    list_preset_timer_audios,
    list_visible_timer_audios,
    save_timer_audio,
    update_timer_audio,
)
from .timer_response_models import TimerAudioDTO, TimerAudiosResponse

logger = logging.getLogger(__name__)


def _presign(s3_key: Optional[str]) -> Optional[str]:
    if not s3_key:
        return None
    try:
        return generate_presigned_access_url(get("AWS_BUCKET_NAME"), s3_key)
    except Exception:
        logger.error(f"Failed to generate presigned URL for media: {s3_key}", exc_info=True)
        return None


def convert_timer_audio_to_dto(timer_audio: Optional[TimerAudio]) -> Optional[TimerAudioDTO]:
    if timer_audio is None:
        return None
    audio_type = (
        TimerAudioType(timer_audio.type.value)
        if hasattr(timer_audio.type, "value")
        else timer_audio.type
    )
    return TimerAudioDTO(
        id=timer_audio.id,
        user_id=timer_audio.user_id,
        type=audio_type,
        name=timer_audio.name,
        audio_url=_presign(timer_audio.audio_s3_key),
        image_url=_presign(timer_audio.image_s3_key),
        created_at=timer_audio.created_at,
        updated_at=timer_audio.updated_at,
    )


def _to_response(audios: List[TimerAudio], total: int, skip: int, limit: int) -> TimerAudiosResponse:
    return TimerAudiosResponse(
        audios=[convert_timer_audio_to_dto(audio) for audio in audios],
        total=total,
        skip=skip,
        limit=limit,
    )


def _validate_admin(token: str) -> None:
    author = validate_cms_author_details(token=token)
    require_super_admin(author)


def _validate_audio_file(file: UploadFile) -> None:
    file_extension = os.path.splitext(file.filename.lower())[1] if file.filename else ""
    if file_extension not in DEFAULTS["ALLOWED_AUDIO_EXTENSIONS"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=INVALID_AUDIO_FILE_FORMAT,
        )
    if hasattr(file, "size") and file.size and file.size > get_int("MAX_AUDIO_FILE_SIZE"):
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=AUDIO_FILE_TOO_LARGE,
        )


def _upload(file: UploadFile, prefix: str) -> str:
    file_extension = os.path.splitext(file.filename.lower())[1] if file.filename else ""
    s3_key = f"{prefix}/{uuid4()}{file_extension}"
    file.file.seek(0)
    upload_file(bucket_name=get("AWS_BUCKET_NAME"), s3_key=s3_key, file=file)
    return s3_key


def _owned_upload(db, timer_audio_id: UUID, user_id: UUID, forbidden_message: str) -> TimerAudio:
    """An audio the caller may modify: their own upload. Presets are Studio's."""
    timer_audio = get_timer_audio_by_id(db, timer_audio_id)
    if not timer_audio or timer_audio.type == TimerAudioType.PRESET:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": NOT_FOUND, "message": TIMER_AUDIO_NOT_FOUND},
        )
    if timer_audio.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"error": FORBIDDEN, "message": forbidden_message},
        )
    return timer_audio


def _preset(db, timer_audio_id: UUID) -> TimerAudio:
    timer_audio = get_timer_audio_by_id(db, timer_audio_id)
    if not timer_audio or timer_audio.type != TimerAudioType.PRESET:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": NOT_FOUND, "message": TIMER_AUDIO_NOT_FOUND},
        )
    return timer_audio


# --------------------------------------------------------------------------
# App: a user's own uploads plus every preset
# --------------------------------------------------------------------------

def list_timer_audios_service(token: str, skip: int = 0, limit: int = 20) -> TimerAudiosResponse:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        audios = list_visible_timer_audios(db, user_id=current_user.id, skip=skip, limit=limit)
        total = count_visible_timer_audios(db, user_id=current_user.id)
        return _to_response(audios, total, skip, limit)


def create_timer_audio_service(
    token: str,
    name: str,
    audio_file: UploadFile,
    image_file: Optional[UploadFile] = None,
) -> TimerAudioDTO:
    """A user's own upload: visible only to them. The image is optional."""
    current_user = validate_and_extract_user_details(token=token)
    _validate_audio_file(audio_file)

    audio_s3_key = _upload(audio_file, "audio/timer_audios")
    image_s3_key = _upload(image_file, "images/timer_audios") if image_file else None

    with SessionLocal() as db:
        try:
            return convert_timer_audio_to_dto(
                save_timer_audio(
                    db,
                    TimerAudio(
                        id=uuid4(),
                        user_id=current_user.id,
                        type=TimerAudioType.USER,
                        name=name,
                        audio_s3_key=audio_s3_key,
                        image_s3_key=image_s3_key,
                    ),
                )
            )
        except Exception:
            # Do not leave the uploaded objects behind if the row never lands.
            delete_file(audio_s3_key)
            if image_s3_key:
                delete_file(image_s3_key)
            raise


def update_timer_audio_service(
    token: str,
    timer_audio_id: UUID,
    name: Optional[str] = None,
    audio_file: Optional[UploadFile] = None,
    image_file: Optional[UploadFile] = None,
) -> TimerAudioDTO:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        timer_audio = _owned_upload(
            db, timer_audio_id, current_user.id, TIMER_AUDIO_UPDATE_NOT_ALLOWED
        )

        if name is not None:
            timer_audio.name = name
        if audio_file is not None:
            _validate_audio_file(audio_file)
            timer_audio.audio_s3_key = _upload(audio_file, "audio/timer_audios")
        if image_file is not None:
            timer_audio.image_s3_key = _upload(image_file, "images/timer_audios")

        return convert_timer_audio_to_dto(update_timer_audio(db, timer_audio))


def delete_timer_audio_service(token: str, timer_audio_id: UUID) -> None:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        timer_audio = _owned_upload(
            db, timer_audio_id, current_user.id, TIMER_AUDIO_DELETE_NOT_ALLOWED
        )
        # Timers referencing it keep working; the FK is ON DELETE SET NULL.
        delete_timer_audio(db, timer_audio)


# --------------------------------------------------------------------------
# Studio: the preset catalogue
# --------------------------------------------------------------------------

def list_preset_timer_audios_service(
    token: str, skip: int = 0, limit: int = 20
) -> TimerAudiosResponse:
    _validate_admin(token)

    with SessionLocal() as db:
        audios = list_preset_timer_audios(db, skip=skip, limit=limit)
        total = count_preset_timer_audios(db)
        return _to_response(audios, total, skip, limit)


def create_preset_timer_audio_service(
    token: str,
    name: str,
    audio_file: UploadFile,
    image_file: Optional[UploadFile] = None,
) -> TimerAudioDTO:
    """A curated preset: no owner, listed to everybody."""
    _validate_admin(token)
    _validate_audio_file(audio_file)

    audio_s3_key = _upload(audio_file, "audio/timer_audio_presets")
    image_s3_key = _upload(image_file, "images/timer_audio_presets") if image_file else None

    with SessionLocal() as db:
        try:
            return convert_timer_audio_to_dto(
                save_timer_audio(
                    db,
                    TimerAudio(
                        id=uuid4(),
                        user_id=None,
                        type=TimerAudioType.PRESET,
                        name=name,
                        audio_s3_key=audio_s3_key,
                        image_s3_key=image_s3_key,
                    ),
                )
            )
        except Exception:
            delete_file(audio_s3_key)
            if image_s3_key:
                delete_file(image_s3_key)
            raise


def update_preset_timer_audio_service(
    token: str,
    timer_audio_id: UUID,
    name: Optional[str] = None,
    audio_file: Optional[UploadFile] = None,
    image_file: Optional[UploadFile] = None,
) -> TimerAudioDTO:
    _validate_admin(token)

    with SessionLocal() as db:
        timer_audio = _preset(db, timer_audio_id)

        if name is not None:
            timer_audio.name = name
        if audio_file is not None:
            _validate_audio_file(audio_file)
            timer_audio.audio_s3_key = _upload(audio_file, "audio/timer_audio_presets")
        if image_file is not None:
            timer_audio.image_s3_key = _upload(image_file, "images/timer_audio_presets")

        return convert_timer_audio_to_dto(update_timer_audio(db, timer_audio))


def delete_preset_timer_audio_service(token: str, timer_audio_id: UUID) -> None:
    _validate_admin(token)

    with SessionLocal() as db:
        delete_timer_audio(db, _preset(db, timer_audio_id))
