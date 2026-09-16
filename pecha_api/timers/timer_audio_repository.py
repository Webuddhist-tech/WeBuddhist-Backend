from sqlalchemy import or_
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from uuid import UUID
from fastapi import HTTPException
from starlette import status

from .timer_audio_enums import TimerAudioType
from .timer_audio_model import TimerAudio
from .response_message import BAD_REQUEST, CONFLICT, TIMER_AUDIO_NAME_ALREADY_USED


def _visible_to(query, user_id: UUID):
    """Presets, plus this user's own uploads. Nobody else's uploads."""
    return query.filter(
        or_(
            TimerAudio.type == TimerAudioType.PRESET,
            TimerAudio.user_id == user_id,
        )
    )


def get_timer_audio_by_id(db: Session, timer_audio_id: UUID) -> Optional[TimerAudio]:
    return db.query(TimerAudio).filter(TimerAudio.id == timer_audio_id).first()


def get_visible_timer_audio_by_id(
    db: Session, timer_audio_id: UUID, user_id: UUID
) -> Optional[TimerAudio]:
    """Someone else's upload reads as missing rather than forbidden, so ids
    cannot be probed."""
    return _visible_to(
        db.query(TimerAudio).filter(TimerAudio.id == timer_audio_id), user_id
    ).first()


def list_visible_timer_audios(
    db: Session, user_id: UUID, skip: int = 0, limit: int = 20
) -> List[TimerAudio]:
    return (
        _visible_to(db.query(TimerAudio), user_id)
        .order_by(TimerAudio.type.asc(), TimerAudio.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def count_visible_timer_audios(db: Session, user_id: UUID) -> int:
    return _visible_to(db.query(TimerAudio), user_id).count()


def list_preset_timer_audios(db: Session, skip: int = 0, limit: int = 20) -> List[TimerAudio]:
    """Studio's catalogue view: presets only, nobody's uploads."""
    return (
        db.query(TimerAudio)
        .filter(TimerAudio.type == TimerAudioType.PRESET)
        .order_by(TimerAudio.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def count_preset_timer_audios(db: Session) -> int:
    return db.query(TimerAudio).filter(TimerAudio.type == TimerAudioType.PRESET).count()


def count_timer_audios_using_media(db: Session, s3_key: str) -> int:
    """How many rows still point at this object, as their audio or as their
    cover. The backfill could hand two rows the same key, so an object is only
    unreachable once this reaches zero."""
    return (
        db.query(TimerAudio)
        .filter(
            or_(
                TimerAudio.audio_s3_key == s3_key,
                TimerAudio.image_s3_key == s3_key,
            )
        )
        .count()
    )


def save_timer_audio(db: Session, timer_audio: TimerAudio) -> TimerAudio:
    try:
        db.add(timer_audio)
        db.commit()
        db.refresh(timer_audio)
        return timer_audio
    except IntegrityError as e:
        db.rollback()
        # The only unique constraint is (user_id, name).
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": CONFLICT, "message": TIMER_AUDIO_NAME_ALREADY_USED},
        ) from e


def update_timer_audio(db: Session, timer_audio: TimerAudio) -> TimerAudio:
    try:
        db.commit()
        db.refresh(timer_audio)
        return timer_audio
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"error": CONFLICT, "message": TIMER_AUDIO_NAME_ALREADY_USED},
        ) from e


def delete_timer_audio(db: Session, timer_audio: TimerAudio) -> None:
    try:
        db.delete(timer_audio)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": BAD_REQUEST, "message": str(e)},
        ) from e
