import os
import re
import logging
from typing import Optional, List
from uuid import UUID, uuid4

from fastapi import HTTPException, UploadFile
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.image_utils import WEBP_CONTENT_TYPE, WEBP_EXTENSION, ImageUtils
from pecha_api.uploads.S3_utils import (
    generate_presigned_access_url,
    upload_bytes,
    upload_file,
    delete_file,
)
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

AUDIO_PREFIX = "audio/ambient_sounds"
IMAGE_PREFIX = "images/ambient_sounds"

# A storage key ends with an extension taken from a user-supplied filename, so
# it is user-influenced data. Anything outside this allowlist -- a newline
# above all -- could forge a second log line, so it is replaced before the key
# reaches the log (S5145).
_UNSAFE_LOG_CHARS = re.compile(r"[^\w./-]")


def _sanitize_for_log(value: Optional[str]) -> str:
    return _UNSAFE_LOG_CHARS.sub("_", str(value))


def generate_ambient_sound_presigned_url(s3_key: Optional[str]) -> Optional[str]:
    if not s3_key:
        return None
    try:
        bucket_name = get("AWS_BUCKET_NAME")
        return generate_presigned_access_url(bucket_name, s3_key)
    except Exception:
        logger.exception(
            "Failed to generate presigned URL for ambient sound: %s",
            _sanitize_for_log(s3_key),
        )
        return None


def convert_ambient_sound_to_dto(ambient_sound: AmbientSound) -> AmbientSoundDTO:
    return AmbientSoundDTO(
        id=ambient_sound.id,
        name=ambient_sound.name,
        url=generate_ambient_sound_presigned_url(ambient_sound.s3_key),
        image_url=generate_ambient_sound_presigned_url(ambient_sound.image_s3_key),
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


def _upload_audio(file: UploadFile) -> str:
    file_extension = os.path.splitext(file.filename.lower())[1] if file.filename else ""
    s3_key = f"{AUDIO_PREFIX}/{uuid4()}{file_extension}"
    file.file.seek(0)
    upload_file(bucket_name=get("AWS_BUCKET_NAME"), s3_key=s3_key, file=file)
    return s3_key


def _upload_image(file: UploadFile) -> str:
    """The cover goes through the same validate-and-compress-to-webp pipeline
    as every other user-supplied image, so a non-image or an oversized file is
    rejected rather than stored behind a presigned URL."""
    compressed_image = ImageUtils().validate_and_compress_image(
        file=file,
        content_type=file.content_type or "image/jpeg",
    )
    s3_key = f"{IMAGE_PREFIX}/{uuid4()}{WEBP_EXTENSION}"
    upload_bytes(
        bucket_name=get("AWS_BUCKET_NAME"),
        s3_key=s3_key,
        file=compressed_image,
        content_type=WEBP_CONTENT_TYPE,
    )
    return s3_key


def _discard(*s3_keys: Optional[str]) -> None:
    """Drop objects uploaded moments ago that never made it onto a committed
    row, and objects a committed row has stopped pointing at. Keys are unique
    per upload, so nothing else is ever pointing at them. Best effort: an
    orphan in the bucket is not worth failing a request over."""
    for s3_key in s3_keys:
        if not s3_key:
            continue
        try:
            delete_file(s3_key)
        except Exception:
            logger.exception(
                "Failed to delete orphaned ambient sound media: %s",
                _sanitize_for_log(s3_key),
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
    file: UploadFile,
    image_file: Optional[UploadFile] = None
) -> AmbientSoundDTO:
    _validate_admin(token)
    _validate_audio_file(file)

    s3_key = _upload_audio(file)
    try:
        image_s3_key = _upload_image(image_file) if image_file else None
    except Exception:
        # A rejected cover must not leave the audio behind.
        _discard(s3_key)
        raise

    with SessionLocal() as db:
        try:
            if is_default:
                unset_other_defaults(db)

            new_ambient_sound = AmbientSound(
                id=uuid4(),
                name=name,
                s3_key=s3_key,
                image_s3_key=image_s3_key,
                is_default=is_default,
                display_order=display_order
            )
            saved_ambient_sound = save_ambient_sound(db, new_ambient_sound)
        except Exception:
            _discard(s3_key, image_s3_key)
            raise
        return convert_ambient_sound_to_dto(saved_ambient_sound)


def update_ambient_sound_service(
    token: str,
    ambient_sound_id: UUID,
    name: Optional[str],
    display_order: Optional[int],
    is_default: Optional[bool],
    file: Optional[UploadFile],
    image_file: Optional[UploadFile] = None
) -> AmbientSoundDTO:
    _validate_admin(token)

    with SessionLocal() as db:
        ambient_sound = get_ambient_sound_by_id(db, ambient_sound_id)
        if not ambient_sound:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": AMBIENT_SOUND_NOT_FOUND}
            )

        # Objects the row is about to stop pointing at. They only go once the
        # replacement has committed; if the write fails first it is the newly
        # uploaded objects that are the orphans instead.
        replaced_keys: List[Optional[str]] = []
        uploaded_keys: List[str] = []

        try:
            if file is not None:
                _validate_audio_file(file)
                replaced_keys.append(ambient_sound.s3_key)
                ambient_sound.s3_key = _upload_audio(file)
                uploaded_keys.append(ambient_sound.s3_key)

            if image_file is not None:
                replaced_keys.append(ambient_sound.image_s3_key)
                ambient_sound.image_s3_key = _upload_image(image_file)
                uploaded_keys.append(ambient_sound.image_s3_key)

            if name is not None:
                ambient_sound.name = name
            if display_order is not None:
                ambient_sound.display_order = display_order
            if is_default is not None:
                if is_default:
                    unset_other_defaults(db, exclude_id=ambient_sound.id)
                ambient_sound.is_default = is_default

            updated_ambient_sound = update_ambient_sound(db, ambient_sound)
        except Exception:
            _discard(*uploaded_keys)
            raise

        dto = convert_ambient_sound_to_dto(updated_ambient_sound)

    _discard(*replaced_keys)

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
        # Timers pointing at it keep working; the FK is ON DELETE SET NULL.
        orphaned_keys = (ambient_sound.s3_key, ambient_sound.image_s3_key)
        delete_ambient_sound(db, ambient_sound)

    _discard(*orphaned_keys)
