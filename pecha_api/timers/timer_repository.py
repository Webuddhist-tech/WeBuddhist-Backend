from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from sqlalchemy import and_, func, or_
from typing import List, Tuple, Optional, Dict
from uuid import UUID
from datetime import datetime
from fastapi import HTTPException
from starlette import status
import _datetime
from .timer_model import Timer
from .timer_history_model import TimerHistory
from .timer_enums import TimerType


def save_timer(db: Session, timer: Timer) -> Timer:
    try:
        db.add(timer)
        db.commit()
        db.refresh(timer)
        return timer
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e.orig)}
        )


def get_timer_by_id(db: Session, timer_id: UUID, include_deleted: bool = False) -> Optional[Timer]:
    query = db.query(Timer).filter(Timer.id == timer_id)
    if not include_deleted:
        query = query.filter(Timer.deleted_at.is_(None))
    return query.first()


def update_timer(db: Session, timer: Timer) -> Timer:
    try:
        db.commit()
        db.refresh(timer)
        return timer
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e.orig)}
        )


def delete_timer(db: Session, timer: Timer) -> None:
    try:
        timer.deleted_at = datetime.now(_datetime.timezone.utc)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e)}
        )


def purge_deleted_timers_older_than(db: Session, cutoff_datetime: datetime) -> int:
    deleted_count = (
        db.query(Timer)
        .filter(Timer.deleted_at.isnot(None), Timer.deleted_at < cutoff_datetime)
        .delete(synchronize_session=False)
    )
    db.commit()
    return deleted_count


def get_timers_by_group(
    db: Session,
    group_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 20,
    user_id: Optional[UUID] = None,
) -> Tuple[List[Timer], int]:
    query = db.query(Timer).filter(Timer.deleted_at.is_(None))
    if group_id:
        query = query.filter(Timer.group_id == group_id)
    if user_id is None:
        # Anonymous catalogue: shared presets only, never anyone's personal rows.
        query = query.filter(Timer.type == TimerType.PRESET)
    else:
        query = _catalogue_plus_caller_timers(query, db, user_id)

    total = query.count()
    timers = query.order_by(Timer.created_at.desc()).offset(skip).limit(limit).all()

    return timers, total


def _catalogue_plus_caller_timers(query, db: Session, user_id: UUID):
    """Presets the caller has not copied, plus every timer they own.

    Other accounts' user_created rows stay out. A copied preset is omitted
    so the personal copy is the only row for that sit.
    """
    copied_preset_ids = (
        db.query(Timer.parent_preset_id)
        .filter(
            Timer.user_id == user_id,
            Timer.parent_preset_id.isnot(None),
            Timer.deleted_at.is_(None),
        )
    )
    return query.filter(
        or_(
            and_(
                Timer.type == TimerType.PRESET,
                ~Timer.id.in_(copied_preset_ids),
            ),
            Timer.user_id == user_id,
        )
    )


def get_user_timers_by_group(
    db: Session,
    user_id: UUID,
    group_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 20
) -> Tuple[List[Timer], int]:

    query = db.query(Timer).filter(Timer.user_id == user_id, Timer.deleted_at.is_(None))
    if group_id:
        query = query.filter(Timer.group_id == group_id)
    
    total = query.count()
    timers = query.order_by(Timer.created_at.desc()).offset(skip).limit(limit).all()
    
    return timers, total


def lock_timer_row(db: Session, timer_id: UUID) -> None:
    """Take a row lock on a timer, serializing writers keyed to that timer.

    Used before creating a user's personal copy of a preset: nothing enforces
    uniqueness on (user_id, parent_preset_id), so two first-time customizations
    of the same preset can otherwise both find nothing and both insert.
    """
    db.query(Timer.id).filter(Timer.id == timer_id).with_for_update().first()


def get_user_timer_by_parent_preset(
    db: Session,
    user_id: UUID,
    parent_preset_id: UUID,
) -> Optional[Timer]:
    return (
        db.query(Timer)
        .filter(
            Timer.user_id == user_id,
            Timer.parent_preset_id == parent_preset_id,
            Timer.deleted_at.is_(None),
        )
        .first()
    )


def get_user_total_duration(db: Session, user_id: UUID) -> int:
    """Total seconds across all of the user's timer sessions."""
    total = (
        db.query(func.sum(TimerHistory.duration_ms))
        .filter(TimerHistory.user_id == user_id)
        .scalar()
    )
    return total or 0


def save_timer_history(db: Session, timer_history: TimerHistory) -> TimerHistory:
    try:
        db.add(timer_history)
        db.commit()
        db.refresh(timer_history)
        return timer_history
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"error": "BAD_REQUEST", "message": str(e.orig)}
        )


def get_user_timer_history(
    db: Session,
    user_id: UUID,
    skip: int = 0,
    limit: int = 20
) -> Tuple[List[Tuple[Timer, int, List[TimerHistory]]], int]:

    timer_ids_with_history = (
        db.query(TimerHistory.timer_id)
        .filter(TimerHistory.user_id == user_id)
        .distinct()
        .subquery()
    )
    
    total = (
        db.query(Timer)
        .filter(Timer.id.in_(timer_ids_with_history), Timer.deleted_at.is_(None))
        .count()
    )

    timers = (
        db.query(Timer)
        .filter(Timer.id.in_(timer_ids_with_history), Timer.deleted_at.is_(None))
        .order_by(Timer.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    
    if not timers:
        return [], 0
    
    timer_ids = [timer.id for timer in timers]
    
    totals_query = (
        db.query(
            TimerHistory.timer_id,
            func.sum(TimerHistory.duration_ms).label('total_duration')
        )
        .filter(
            TimerHistory.timer_id.in_(timer_ids),
            TimerHistory.user_id == user_id
        )
        .group_by(TimerHistory.timer_id)
        .all()
    )
    totals_map = {row.timer_id: row.total_duration or 0 for row in totals_query}
    
    all_sessions = (
        db.query(TimerHistory)
        .filter(
            TimerHistory.timer_id.in_(timer_ids),
            TimerHistory.user_id == user_id
        )
        .order_by(TimerHistory.created_at.desc())
        .all()
    )
    
    sessions_map: Dict[UUID, List[TimerHistory]] = {}
    for session in all_sessions:
        if session.timer_id not in sessions_map:
            sessions_map[session.timer_id] = []
        sessions_map[session.timer_id].append(session)
    
    result = []
    for timer in timers:
        total_time = totals_map.get(timer.id, 0)
        sessions = sessions_map.get(timer.id, [])
        result.append((timer, total_time, sessions))
    
    return result, total
