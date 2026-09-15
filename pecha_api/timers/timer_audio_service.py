import logging
from typing import Optional
from uuid import UUID, uuid4

from fastapi import HTTPException
from starlette import status

from ..db.database import SessionLocal
from ..users.users_service import validate_and_extract_user_details
from ..uploads.S3_utils import generate_presigned_access_url
from ..config import get
from .response_message import (
    FORBIDDEN,
    NOT_FOUND,
    TIMER_AUDIO_DELETE_NOT_ALLOWED,
    TIMER_AUDIO_NOT_FOUND,
    TIMER_AUDIO_UPDATE_NOT_ALLOWED,
)
from .timer_audio_model import TimerAudio
from .timer_audio_repository import (
    count_timer_audios,
    delete_timer_audio,
    get_timer_audio_by_id,
    list_timer_audios,
    save_timer_audio,
    update_timer_audio,
)
from .timer_response_models import (
    CreateTimerAudioRequest,
    TimerAudioDTO,
    TimerAudiosResponse,
    UpdateTimerAudioRequest,
)

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
    return TimerAudioDTO(
        id=timer_audio.id,
        user_id=timer_audio.user_id,
        name=timer_audio.name,
        audio_url=_presign(timer_audio.audio_s3_key),
        image_url=_presign(timer_audio.image_s3_key),
        created_at=timer_audio.created_at,
        updated_at=timer_audio.updated_at,
    )


def _get_owned_audio(db, timer_audio_id: UUID, user_id: UUID, forbidden_message: str) -> TimerAudio:
    timer_audio = get_timer_audio_by_id(db, timer_audio_id)
    if not timer_audio:
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


def list_timer_audios_service(skip: int = 0, limit: int = 20) -> TimerAudiosResponse:
    """The whole catalogue, whoever uploaded it, so a user can pick any of them."""
    with SessionLocal() as db:
        audios = list_timer_audios(db, skip=skip, limit=limit)
        total = count_timer_audios(db)
        return TimerAudiosResponse(
            audios=[convert_timer_audio_to_dto(audio) for audio in audios],
            total=total,
            skip=skip,
            limit=limit,
        )


def create_timer_audio_service(token: str, request: CreateTimerAudioRequest) -> TimerAudioDTO:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        timer_audio = TimerAudio(
            id=uuid4(),
            user_id=current_user.id,
            name=request.name,
            audio_s3_key=request.audio_s3_key,
            image_s3_key=request.image_s3_key,
        )
        saved = save_timer_audio(db, timer_audio)
        return convert_timer_audio_to_dto(saved)


def update_timer_audio_service(
    token: str, timer_audio_id: UUID, request: UpdateTimerAudioRequest
) -> TimerAudioDTO:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        timer_audio = _get_owned_audio(
            db, timer_audio_id, current_user.id, TIMER_AUDIO_UPDATE_NOT_ALLOWED
        )

        if request.name is not None:
            timer_audio.name = request.name
        # Both keys are NOT NULL, so they can be replaced but never cleared:
        # that is what keeps every audio paired with an image.
        if request.audio_s3_key is not None:
            timer_audio.audio_s3_key = request.audio_s3_key
        if request.image_s3_key is not None:
            timer_audio.image_s3_key = request.image_s3_key

        updated = update_timer_audio(db, timer_audio)
        return convert_timer_audio_to_dto(updated)


def delete_timer_audio_service(token: str, timer_audio_id: UUID) -> None:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        timer_audio = _get_owned_audio(
            db, timer_audio_id, current_user.id, TIMER_AUDIO_DELETE_NOT_ALLOWED
        )
        # Timers referencing it keep working; the FK is ON DELETE SET NULL.
        delete_timer_audio(db, timer_audio)
