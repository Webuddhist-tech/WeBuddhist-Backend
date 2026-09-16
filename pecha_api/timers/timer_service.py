from typing import Optional, List
from uuid import UUID, uuid4
import logging
import _datetime
from _datetime import datetime, timedelta

from fastapi import HTTPException
from starlette import status
from ..db.database import SessionLocal
from ..config import get_int
from ..users.users_service import validate_and_extract_user_details
from pecha_api.daily_log.daily_log_cache_service import schedule_invalidate_user_stats_cache
from pecha_api.ambient_sounds.ambient_sound_repository import get_ambient_sound_by_id
from .timer_repository import (
    get_timers_by_group,
    get_user_timers_by_group,
    save_timer,
    get_timer_by_id,
    update_timer,
    delete_timer,
    save_timer_history,
    get_user_timer_history,
    purge_deleted_timers_older_than
)
from .timer_response_models import (
    TimersResponse,
    TimerDTO,
    CreateTimerRequest,
    UpdateTimerRequest,
    RecordTimerStopRequest,
    RecordTimerStopResponse,
    TimerHistoryResponse,
    TimerHistoryDTO,
    TimerSessionDTO
)
from .timer_model import Timer
from .timer_history_model import TimerHistory
from .timer_enums import TimerType
from .response_message import (
    NOT_FOUND,
    FORBIDDEN,
    CONFLICT,
    TIMER_NOT_FOUND,
    TIMER_UPDATE_NOT_ALLOWED,
    TIMER_DELETE_NOT_ALLOWED,
    ONLY_USER_TIMERS_CAN_BE_UPDATED,
    ONLY_USER_TIMERS_CAN_BE_DELETED,
    AMBIENT_SOUND_NOT_FOUND,
    PARENT_PRESET_NOT_FOUND,
    TIMER_NOT_DELETED,
    TIMER_RESTORE_WINDOW_EXPIRED
)

logger = logging.getLogger(__name__)




def convert_timer_to_dto(timer: Timer) -> TimerDTO:
    timer_type = TimerType(timer.type.value) if hasattr(timer.type, 'value') else timer.type
    return TimerDTO(
        id=timer.id,
        user_id=timer.user_id,
        group_id=timer.group_id,
        type=timer_type,
        name=timer.name,
        description=timer.description,
        duration=timer.duration,
        ambient_sound_id=timer.ambient_sound_id,
        bell_at_start=timer.bell_at_start,
        bell_at_end=timer.bell_at_end,
        parent_preset_id=timer.parent_preset_id,
        created_at=timer.created_at,
        updated_at=timer.updated_at
    )


def convert_timers_to_dtos(timers: List[Timer]) -> List[TimerDTO]:
    return [convert_timer_to_dto(timer) for timer in timers]


def is_user_created_timer(timer: Timer) -> bool:
    timer_type = timer.type.value if hasattr(timer.type, 'value') else timer.type
    return timer_type == TimerType.USER.value


def _validate_ambient_sound(db, ambient_sound_id: Optional[UUID]) -> None:
    if ambient_sound_id is None:
        return
    ambient_sound = get_ambient_sound_by_id(db, ambient_sound_id)
    if not ambient_sound:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": NOT_FOUND, "message": AMBIENT_SOUND_NOT_FOUND}
        )


def _validate_parent_preset(db, parent_preset_id: Optional[UUID]) -> None:
    if parent_preset_id is None:
        return
    parent_preset = get_timer_by_id(db, parent_preset_id)
    if not parent_preset or not (
        (parent_preset.type.value if hasattr(parent_preset.type, 'value') else parent_preset.type) == TimerType.PRESET.value
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": NOT_FOUND, "message": PARENT_PRESET_NOT_FOUND}
        )


def get_all_timers_service(
    group_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 20
) -> TimersResponse:
    with SessionLocal() as db:
        timers, total = get_timers_by_group(db, group_id, skip, limit)
        return TimersResponse(
            timers=convert_timers_to_dtos(timers),
            total=total,
            skip=skip,
            limit=limit
        )


def get_user_timers_service(
    user_id: UUID,
    group_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 20
) -> TimersResponse:
    with SessionLocal() as db:
        timers, total = get_user_timers_by_group(db, user_id, group_id, skip, limit)
        return TimersResponse(
            timers=convert_timers_to_dtos(timers),
            total=total,
            skip=skip,
            limit=limit
        )


def create_timer_service(token: str, request: CreateTimerRequest) -> TimerDTO:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        _validate_ambient_sound(db, request.ambient_sound_id)
        _validate_parent_preset(db, request.parent_preset_id)

        new_timer = Timer(
            id=uuid4(),
            user_id=current_user.id,
            group_id=request.group_id,
            type=TimerType.USER,
            name=request.name,
            description=request.description,
            duration=request.duration,
            ambient_sound_id=request.ambient_sound_id,
            bell_at_start=request.bell_at_start,
            bell_at_end=request.bell_at_end,
            parent_preset_id=request.parent_preset_id
        )

        saved_timer = save_timer(db, new_timer)
        return convert_timer_to_dto(saved_timer)


def update_timer_service(token: str, timer_id: UUID, request: UpdateTimerRequest) -> TimerDTO:
    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        timer = get_timer_by_id(db, timer_id)
        
        if not timer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": TIMER_NOT_FOUND}
            )
        
        if timer.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": TIMER_UPDATE_NOT_ALLOWED}
            )
        
        if not is_user_created_timer(timer):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": ONLY_USER_TIMERS_CAN_BE_UPDATED}
            )

        ambient_sound_id_provided = "ambient_sound_id" in request.model_fields_set
        if ambient_sound_id_provided and request.ambient_sound_id is not None:
            _validate_ambient_sound(db, request.ambient_sound_id)

        if request.name is not None:
            timer.name = request.name
        if request.description is not None:
            timer.description = request.description
        if request.duration is not None:
            timer.duration = request.duration
        # Distinguish "omitted" from an explicit null, so the sound can be
        # detached from a timer as well as swapped.
        if ambient_sound_id_provided:
            timer.ambient_sound_id = request.ambient_sound_id
        if request.bell_at_start is not None:
            timer.bell_at_start = request.bell_at_start
        if request.bell_at_end is not None:
            timer.bell_at_end = request.bell_at_end


        updated_timer = update_timer(db, timer)
        return convert_timer_to_dto(updated_timer)


def delete_timer_service(token: str, timer_id: UUID) -> None:
    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        timer = get_timer_by_id(db, timer_id)
        
        if not timer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": TIMER_NOT_FOUND}
            )
        
        if timer.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": TIMER_DELETE_NOT_ALLOWED}
            )
        
        if not is_user_created_timer(timer):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": ONLY_USER_TIMERS_CAN_BE_DELETED}
            )
        
        delete_timer(db, timer)


def restore_timer_service(token: str, timer_id: UUID) -> TimerDTO:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        timer = get_timer_by_id(db, timer_id, include_deleted=True)

        if not timer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": TIMER_NOT_FOUND}
            )

        if timer.user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": FORBIDDEN, "message": TIMER_UPDATE_NOT_ALLOWED}
            )

        if timer.deleted_at is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": CONFLICT, "message": TIMER_NOT_DELETED}
            )

        retention_days = get_int("TIMER_DELETED_RETENTION_DAYS")
        cutoff = datetime.now(_datetime.timezone.utc) - timedelta(days=retention_days)
        if timer.deleted_at < cutoff:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": CONFLICT, "message": TIMER_RESTORE_WINDOW_EXPIRED}
            )

        timer.deleted_at = None
        restored_timer = update_timer(db, timer)
        return convert_timer_to_dto(restored_timer)


def record_timer_stop_service(token: str, request: RecordTimerStopRequest) -> RecordTimerStopResponse:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        timer = get_timer_by_id(db, request.timer_id)
        if not timer:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": NOT_FOUND, "message": TIMER_NOT_FOUND}
            )

        timer_history = TimerHistory(
            id=uuid4(),
            timer_id=request.timer_id,
            user_id=current_user.id,
            duration_ms=request.duration,
            created_at=datetime.now(_datetime.timezone.utc)
        )

        save_timer_history(db, timer_history)
        response = RecordTimerStopResponse(
            timer_id=timer.id,
            name=timer.name,
            duration_ms=request.duration
        )

    schedule_invalidate_user_stats_cache(user_id=current_user.id)
    return response


def purge_deleted_timers(retention_days: int) -> int:
    if retention_days < 1:
        raise ValueError(f"retention_days must be a positive integer, got {retention_days}")
    cutoff = datetime.now(_datetime.timezone.utc) - timedelta(days=retention_days)
    with SessionLocal() as db:
        deleted_count = purge_deleted_timers_older_than(db, cutoff)
        logger.info("Purged %s soft-deleted timer(s) older than %s", deleted_count, cutoff)
        return deleted_count


def get_timer_history_service(
    token: str,
    skip: int = 0,
    limit: int = 20
) -> TimerHistoryResponse:
    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        history_data, total = get_user_timer_history(db, current_user.id, skip, limit)
        
        timers = []
        for timer, total_time_spent, sessions in history_data:
            timer_history_dto = TimerHistoryDTO(
                timer_id=timer.id,
                name=timer.name,
                description=timer.description,
                actual_duration=timer.duration,
                total_time_spent=total_time_spent,
                sessions=[
                    TimerSessionDTO(
                        duration=session.duration_ms,
                        created_at=session.created_at
                    )
                    for session in sessions
                ]
            )
            timers.append(timer_history_dto)
        
        return TimerHistoryResponse(
            timers=timers,
            total=total,
            skip=skip,
            limit=limit
        )
