import logging
import os
from typing import List, Optional
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from starlette import status

from ..config import get, get_int, DEFAULTS
from ..db.database import SessionLocal
from ..image_utils import WEBP_CONTENT_TYPE, WEBP_EXTENSION, ImageUtils
from ..uploads.S3_utils import (
    delete_file,
    generate_presigned_access_url,
    upload_bytes,
    upload_file,
)
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
    count_timer_audios_using_media,
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


def _upload_image(file: UploadFile, prefix: str) -> str:
    """Covers go through the same validate-and-compress-to-webp pipeline as
    every other user-supplied image, so a non-image or an oversized file is
    rejected rather than stored behind a presigned URL."""
    compressed_image = ImageUtils().validate_and_compress_image(
        file=file,
        content_type=file.content_type or "image/jpeg",
    )
    s3_key = f"{prefix}/{uuid4()}{WEBP_EXTENSION}"
    upload_bytes(
        bucket_name=get("AWS_BUCKET_NAME"),
        s3_key=s3_key,
        file=compressed_image,
        content_type=WEBP_CONTENT_TYPE,
    )
    return s3_key


def _discard(*s3_keys: Optional[str]) -> None:
    """Drop objects we uploaded moments ago and then failed to attach to a row.
    Their keys are freshly minted, so nothing else can be pointing at them.
    Best effort: an orphan in the bucket is not worth failing a request over."""
    for s3_key in s3_keys:
        if not s3_key:
            continue
        try:
            delete_file(s3_key)
        except Exception:
            logger.error(f"Failed to delete orphaned media: {s3_key}", exc_info=True)


def _discard_if_unreferenced(db, *s3_keys: Optional[str]) -> None:
    """Drop stored objects that the row just detached from or deleted.

    Those keys are not necessarily exclusive: the backfill grouped by
    (user, audio key), so two users who shared a legacy audio key hold the same
    audio_s3_key, and a cover picked with MIN(image_url) can be shared between
    audio rows. Deleting on that shared key would blank out media another
    catalogue entry still shows, so an object only goes once the last row
    referencing it is gone. Callers run this after the write has committed, so
    the count reflects the new state."""
    for s3_key in s3_keys:
        if not s3_key:
            continue
        try:
            if count_timer_audios_using_media(db, s3_key) > 0:
                continue
            delete_file(s3_key)
        except Exception:
            logger.error(f"Failed to delete orphaned media: {s3_key}", exc_info=True)


def _apply_media_update(
    db,
    timer_audio: TimerAudio,
    name: Optional[str],
    audio_file: Optional[UploadFile],
    image_file: Optional[UploadFile],
    audio_prefix: str,
    image_prefix: str,
) -> TimerAudioDTO:
    """Replaced objects leave the bucket, but only once the row that stopped
    pointing at them has committed. If anything fails first, the replacements
    are the orphans and they go instead."""
    replaced_keys: List[Optional[str]] = []
    uploaded_keys: List[str] = []

    try:
        if name is not None:
            timer_audio.name = name
        if audio_file is not None:
            _validate_audio_file(audio_file)
            replaced_keys.append(timer_audio.audio_s3_key)
            timer_audio.audio_s3_key = _upload(audio_file, audio_prefix)
            uploaded_keys.append(timer_audio.audio_s3_key)
        if image_file is not None:
            replaced_keys.append(timer_audio.image_s3_key)
            timer_audio.image_s3_key = _upload_image(image_file, image_prefix)
            uploaded_keys.append(timer_audio.image_s3_key)

        dto = convert_timer_audio_to_dto(update_timer_audio(db, timer_audio))
    except Exception:
        _discard(*uploaded_keys)
        raise

    _discard_if_unreferenced(db, *replaced_keys)
    return dto


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
    try:
        image_s3_key = _upload_image(image_file, "images/timer_audios") if image_file else None
    except Exception:
        # A rejected cover must not leave the audio behind.
        _discard(audio_s3_key)
        raise

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
            _discard(audio_s3_key, image_s3_key)
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

        return _apply_media_update(
            db,
            timer_audio,
            name=name,
            audio_file=audio_file,
            image_file=image_file,
            audio_prefix="audio/timer_audios",
            image_prefix="images/timer_audios",
        )


def delete_timer_audio_service(token: str, timer_audio_id: UUID) -> None:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        timer_audio = _owned_upload(
            db, timer_audio_id, current_user.id, TIMER_AUDIO_DELETE_NOT_ALLOWED
        )
        orphaned_keys = (timer_audio.audio_s3_key, timer_audio.image_s3_key)
        # Timers referencing it keep working; the FK is ON DELETE SET NULL.
        delete_timer_audio(db, timer_audio)
        # Only once the row is gone, and only if no other row shares the key.
        _discard_if_unreferenced(db, *orphaned_keys)


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
    try:
        image_s3_key = _upload_image(image_file, "images/timer_audio_presets") if image_file else None
    except Exception:
        _discard(audio_s3_key)
        raise

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
            _discard(audio_s3_key, image_s3_key)
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

        return _apply_media_update(
            db,
            timer_audio,
            name=name,
            audio_file=audio_file,
            image_file=image_file,
            audio_prefix="audio/timer_audio_presets",
            image_prefix="images/timer_audio_presets",
        )


def delete_preset_timer_audio_service(token: str, timer_audio_id: UUID) -> None:
    _validate_admin(token)

    with SessionLocal() as db:
        timer_audio = _preset(db, timer_audio_id)
        orphaned_keys = (timer_audio.audio_s3_key, timer_audio.image_s3_key)
        delete_timer_audio(db, timer_audio)
        _discard_if_unreferenced(db, *orphaned_keys)
