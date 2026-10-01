from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from starlette import status
from uuid import UUID
from typing import Optional, List, Tuple
from datetime import time
import _datetime
from _datetime import datetime

from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.plans.response_message import BAD_REQUEST
from pecha_api.plans.plans_models import Plan
from .routines_models import Routine, RoutineTimeBlock, RoutineSession
from .routines_enums import SessionType


def get_routine_by_user_id(
    db: Session, user_id: UUID, include_deleted: bool = False
) -> Optional[Routine]:

    query = db.query(Routine).filter(Routine.user_id == user_id)
    
    if not include_deleted:
        query = query.filter(Routine.deleted_at.is_(None))
    
    return query.first()


def get_plans_by_ids(db: Session, plan_ids: List[UUID]) -> List[Plan]:
    if not plan_ids:
        return []
    return db.query(Plan).filter(Plan.id.in_(plan_ids)).all()


def get_routine_by_id_and_user(
    db: Session, routine_id: UUID, user_id: UUID
) -> Optional[Routine]:
    return (
        db.query(Routine)
        .filter(
            Routine.id == routine_id,
            Routine.user_id == user_id,
            Routine.deleted_at.is_(None),
        )
        .first()
    )


def time_block_exists_for_routine(db: Session, routine_id: UUID, time: str) -> bool:
    return (
        db.query(RoutineTimeBlock)
        .filter(
            RoutineTimeBlock.routine_id == routine_id,
            RoutineTimeBlock.time == time,
            RoutineTimeBlock.deleted_at.is_(None),
        )
        .first()
        is not None
    )


def save_routine(db: Session, routine: Routine) -> Routine:
    try:
        db.add(routine)
        db.commit()
        db.refresh(routine)
        return routine
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ResponseError(error=BAD_REQUEST, message=str(e.orig)).model_dump(),
        )


def save_time_block(db: Session, time_block: RoutineTimeBlock) -> RoutineTimeBlock:
    try:
        db.add(time_block)
        db.commit()
        db.refresh(time_block)
        return time_block
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ResponseError(error=BAD_REQUEST, message=str(e.orig)).model_dump(),
        )


def save_sessions(db: Session, sessions: List[RoutineSession]) -> List[RoutineSession]:
    try:
        db.add_all(sessions)
        db.commit()
        for session in sessions:
            db.refresh(session)
        return sessions
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ResponseError(error=BAD_REQUEST, message=str(e.orig)).model_dump(),
        )


def get_time_block_by_id_and_routine(
    db: Session, time_block_id: UUID, routine_id: UUID
) -> Optional[RoutineTimeBlock]:
    return (
        db.query(RoutineTimeBlock)
        .filter(
            RoutineTimeBlock.id == time_block_id,
            RoutineTimeBlock.routine_id == routine_id,
            RoutineTimeBlock.deleted_at.is_(None),
        )
        .first()
    )


def get_plan_source_ids_by_time_block_id(
    db: Session, time_block_id: UUID
) -> List[UUID]:
    sessions = (
        db.query(RoutineSession.source_id)
        .filter(
            RoutineSession.time_block_id == time_block_id,
            RoutineSession.session_type == SessionType.PLAN,
        )
        .all()
    )
    return [UUID(s.source_id) for s in sessions]


def soft_delete_time_block(db: Session, time_block: RoutineTimeBlock) -> None:
    time_block.deleted_at = datetime.now(_datetime.timezone.utc)
    db.commit()


def get_time_block_by_id(db: Session, time_block_id: UUID) -> Optional[RoutineTimeBlock]:
    return (
        db.query(RoutineTimeBlock)
        .filter(
            RoutineTimeBlock.id == time_block_id,
            RoutineTimeBlock.deleted_at.is_(None),
        )
        .first()
    )


def get_time_block_by_routine_and_time(db: Session, routine_id: UUID, time: str, exclude_time_block_id: Optional[UUID] = None) -> Optional[RoutineTimeBlock]:
    query = db.query(RoutineTimeBlock).filter(
        RoutineTimeBlock.routine_id == routine_id,
        RoutineTimeBlock.time == time,
        RoutineTimeBlock.deleted_at.is_(None),
    )
    if exclude_time_block_id:
        query = query.filter(RoutineTimeBlock.id != exclude_time_block_id)
    return query.first()


def delete_sessions_by_time_block_id(db: Session, time_block_id: UUID) -> None:
    db.query(RoutineSession).filter(
        RoutineSession.time_block_id == time_block_id
    ).delete()
    db.commit()


def update_time_block(
    db: Session,
    time_block: RoutineTimeBlock,
    time: str,
    time_utc: time,
    time_int: int,
    notification_enabled: bool,
    title: Optional[str] = None,
) -> RoutineTimeBlock:
    try:
        time_block.time = time
        time_block.time_utc = time_utc
        time_block.time_int = time_int
        time_block.title = title
        time_block.notification_enabled = notification_enabled
        db.commit()
        db.refresh(time_block)
        return time_block
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ResponseError(error=BAD_REQUEST, message=str(e.orig)).model_dump(),
        )


def get_time_blocks(db: Session,routine_id: UUID,include_deleted: bool = False,order_by_field=None,order_desc: bool = False,skip: int = 0,limit: int = 20) -> Tuple[List[RoutineTimeBlock], int]:

    query = db.query(RoutineTimeBlock).filter(RoutineTimeBlock.routine_id == routine_id)

    if not include_deleted:
        query = query.filter(RoutineTimeBlock.deleted_at.is_(None))

    if order_by_field is not None:
        query = query.order_by(order_by_field.desc() if order_desc else order_by_field)

    total = query.count()
    time_blocks = query.offset(skip).limit(limit).all()

    return time_blocks, total


def get_sessions_by_time_block_ids(db: Session, time_block_ids: List[UUID], order_by_field=None, order_desc: bool = False) -> List[RoutineSession]:
    if not time_block_ids:
        return []
    
    query = db.query(RoutineSession).filter(RoutineSession.time_block_id.in_(time_block_ids))
    
    if order_by_field is not None:
        query = query.order_by(order_by_field.desc() if order_desc else order_by_field)
    
    return query.all()


def get_time_blocks_containing_series(
    db: Session, user_id: UUID, series_id: UUID
) -> List[RoutineTimeBlock]:
    return (
        db.query(RoutineTimeBlock)
        .join(Routine, RoutineTimeBlock.routine_id == Routine.id)
        .join(RoutineSession, RoutineSession.time_block_id == RoutineTimeBlock.id)
        .filter(
            Routine.user_id == user_id,
            Routine.deleted_at.is_(None),
            RoutineTimeBlock.deleted_at.is_(None),
            RoutineSession.session_type == SessionType.SERIES,
            RoutineSession.source_id == str(series_id),
        )
        .all()
    )


def get_time_blocks_containing_plan(db: Session, user_id: UUID, plan_id: UUID) -> List[RoutineTimeBlock]:

    return (
        db.query(RoutineTimeBlock)
        .join(Routine, RoutineTimeBlock.routine_id == Routine.id)
        .join(RoutineSession, RoutineSession.time_block_id == RoutineTimeBlock.id)
        .filter(
            Routine.user_id == user_id,
            Routine.deleted_at.is_(None),
            RoutineTimeBlock.deleted_at.is_(None),
            RoutineSession.session_type == SessionType.PLAN,
            RoutineSession.source_id == str(plan_id),
        )
        .all()
    )


def get_max_display_order_in_time_block(db: Session, time_block_id: UUID) -> int:
    """
    Get the maximum display_order value for sessions in a time block.
    Returns 0 if no sessions exist.
    """
    from sqlalchemy import func
    result = db.query(func.max(RoutineSession.display_order)).filter(
        RoutineSession.time_block_id == time_block_id
    ).scalar()
    return result if result is not None else 0


def add_plan_session_to_time_block(db: Session, time_block_id: UUID, plan_id: UUID, display_order: int) -> RoutineSession:

    session = RoutineSession(
        time_block_id=time_block_id,
        session_type=SessionType.PLAN,
        source_id=str(plan_id),
        display_order=display_order,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def get_series_source_ids_by_time_block_id(
    db: Session, time_block_id: UUID
) -> List[UUID]:
    sessions = (
        db.query(RoutineSession.source_id)
        .filter(
            RoutineSession.time_block_id == time_block_id,
            RoutineSession.session_type == SessionType.SERIES,
        )
        .all()
    )
    return [UUID(s.source_id) for s in sessions]


def get_existing_plan_source_ids(db: Session, routine_id: UUID) -> List[UUID]:
    """Get all plan source_ids in a routine."""
    sessions = (
        db.query(RoutineSession.source_id)
        .join(RoutineTimeBlock, RoutineSession.time_block_id == RoutineTimeBlock.id)
        .filter(
            RoutineTimeBlock.routine_id == routine_id,
            RoutineTimeBlock.deleted_at.is_(None),
            RoutineSession.session_type == SessionType.PLAN,
        )
        .all()
    )
    return [UUID(s.source_id) for s in sessions]


def get_existing_plan_source_ids_in_routine(
    db: Session, routine_id: UUID, exclude_time_block_id: Optional[UUID] = None
) -> List[UUID]:
    """Get all plan source_ids in a routine, optionally excluding a time block."""
    query = (
        db.query(RoutineSession.source_id)
        .join(RoutineTimeBlock, RoutineSession.time_block_id == RoutineTimeBlock.id)
        .filter(
            RoutineTimeBlock.routine_id == routine_id,
            RoutineTimeBlock.deleted_at.is_(None),
            RoutineSession.session_type == SessionType.PLAN,
        )
    )
    if exclude_time_block_id:
        query = query.filter(RoutineTimeBlock.id != exclude_time_block_id)
    return [UUID(row[0]) for row in query.all()]


def get_existing_collection_source_ids(
    db: Session,
    routine_id: UUID,
    session_type: SessionType = SessionType.RECITATION_COLLECTION,
) -> List[UUID]:
    """Get all collection source_ids of a given type in a routine."""
    sessions = (
        db.query(RoutineSession.source_id)
        .join(RoutineTimeBlock, RoutineSession.time_block_id == RoutineTimeBlock.id)
        .filter(
            RoutineTimeBlock.routine_id == routine_id,
            RoutineTimeBlock.deleted_at.is_(None),
            RoutineSession.session_type == session_type,
        )
        .all()
    )
    return [UUID(s.source_id) for s in sessions]


def get_existing_collection_source_ids_in_routine(
    db: Session,
    routine_id: UUID,
    exclude_time_block_id: Optional[UUID] = None,
    session_type: SessionType = SessionType.RECITATION_COLLECTION,
) -> List[UUID]:
    """Get collection source_ids of a given type in a routine, optionally excluding a time block."""
    query = (
        db.query(RoutineSession.source_id)
        .join(RoutineTimeBlock, RoutineSession.time_block_id == RoutineTimeBlock.id)
        .filter(
            RoutineTimeBlock.routine_id == routine_id,
            RoutineTimeBlock.deleted_at.is_(None),
            RoutineSession.session_type == session_type,
        )
    )
    if exclude_time_block_id:
        query = query.filter(RoutineTimeBlock.id != exclude_time_block_id)
    return [UUID(row[0]) for row in query.all()]


def get_collection_source_ids_by_time_block_id(
    db: Session,
    time_block_id: UUID,
    session_type: SessionType = SessionType.RECITATION_COLLECTION,
) -> List[UUID]:
    """Get collection source_ids of a given type for a specific time block."""
    sessions = (
        db.query(RoutineSession.source_id)
        .filter(
            RoutineSession.time_block_id == time_block_id,
            RoutineSession.session_type == session_type,
        )
        .all()
    )
    return [UUID(s.source_id) for s in sessions]


def get_routine_series_and_recitation_counts(
    db: Session, routine_id: UUID
) -> Tuple[int, int]:
    sessions = (
        db.query(RoutineSession.session_type, RoutineSession.source_id)
        .join(RoutineTimeBlock, RoutineSession.time_block_id == RoutineTimeBlock.id)
        .filter(
            RoutineTimeBlock.routine_id == routine_id,
            RoutineTimeBlock.deleted_at.is_(None),
        )
        .all()
    )

    # Use sets to count unique source_ids
    series_source_ids = {
        session.source_id
        for session in sessions
        if session.session_type == SessionType.SERIES and session.source_id is not None
    }
    plan_source_ids = {
        session.source_id
        for session in sessions
        if session.session_type == SessionType.PLAN and session.source_id is not None
    }
    recitation_source_ids = {
        session.source_id
        for session in sessions
        if session.session_type
        in (
            SessionType.RECITATION,
            SessionType.RECITATION_COLLECTION,
            SessionType.GROUP_RECITATION_COLLECTION,
        )
    }

    return len(series_source_ids) + len(plan_source_ids), len(recitation_source_ids)
