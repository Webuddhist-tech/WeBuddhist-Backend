from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from uuid import UUID
from fastapi import HTTPException
from starlette import status

from .timer_audio_model import TimerAudio
from .response_message import BAD_REQUEST, CONFLICT, TIMER_AUDIO_NAME_ALREADY_USED


def get_timer_audio_by_id(db: Session, timer_audio_id: UUID) -> Optional[TimerAudio]:
    return db.query(TimerAudio).filter(TimerAudio.id == timer_audio_id).first()


def list_timer_audios(db: Session, skip: int = 0, limit: int = 20) -> List[TimerAudio]:
    """Every audio, whoever uploaded it: the catalogue is shared."""
    return (
        db.query(TimerAudio)
        .order_by(TimerAudio.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )


def count_timer_audios(db: Session) -> int:
    return db.query(TimerAudio).count()


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
