from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from typing import List, Optional
from uuid import UUID
from fastapi import HTTPException
from starlette import status
from .ambient_sound_model import AmbientSound


def get_ambient_sound_by_id(db: Session, ambient_sound_id: UUID) -> Optional[AmbientSound]:
    return db.query(AmbientSound).filter(AmbientSound.id == ambient_sound_id).first()


def list_ambient_sounds(db: Session) -> List[AmbientSound]:
    return db.query(AmbientSound).order_by(AmbientSound.display_order.asc()).all()


def save_ambient_sound(db: Session, ambient_sound: AmbientSound) -> AmbientSound:
    try:
        db.add(ambient_sound)
        db.commit()
        db.refresh(ambient_sound)
        return ambient_sound
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e.orig)}
        )


def update_ambient_sound(db: Session, ambient_sound: AmbientSound) -> AmbientSound:
    try:
        db.commit()
        db.refresh(ambient_sound)
        return ambient_sound
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e.orig)}
        )


def delete_ambient_sound(db: Session, ambient_sound: AmbientSound) -> None:
    try:
        db.delete(ambient_sound)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e)}
        )


def unset_other_defaults(db: Session, exclude_id: Optional[UUID] = None) -> None:
    query = db.query(AmbientSound).filter(AmbientSound.is_default.is_(True))
    if exclude_id is not None:
        query = query.filter(AmbientSound.id != exclude_id)
    query.update({AmbientSound.is_default: False}, synchronize_session=False)
    db.commit()
