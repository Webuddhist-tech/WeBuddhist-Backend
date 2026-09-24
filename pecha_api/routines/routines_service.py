import asyncio
import logging

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from starlette import status
from typing import List, Dict, NoReturn, Optional
from uuid import UUID

from pecha_api.config import TIME_FORMAT_PATTERN, get
from pecha_api.plans.authors.plan_authors_service import get_image_url, safe_get_image_url
from pecha_api.plans.media.media_response_models import ImageUrlModel
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.db.database import SessionLocal
from pecha_api.users.users_service import validate_and_extract_user_details
from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.plans.response_message import BAD_REQUEST
from pecha_api.texts.texts_openpecha_service import get_text_by_id_from_openpecha
from pecha_api.texts.texts_openpecha_api import fetch_edition_text_id
from pecha_api.plans.users.plan_users_models import UserPlanProgress
from pecha_api.plans.users.recitation_collection.recitation_collection_models import (
    RecitationCollection,
)
from pecha_api.plans.users.recitation_collection.recitation_collection_repository import (
    get_collection_item_counts as get_recitation_collection_item_counts,
)
from pecha_api.group_recitation_collection.models import (
    GroupRecitationCollection,
    GroupRecitationCollectionItem,
)
from pecha_api.plans.plans_enums import UserPlanStatus
from datetime import datetime, time, timezone
from pecha_api.plans.users.plan_users_progress_repository import (
    get_plan_progress_by_user_id_and_plan_ids,
)
from pecha_api.plans.shared.metadata_utils import filter_by_language_with_fallback
from pecha_api.timezone_utils import (
    hhmm_to_time_int,
    local_hhmm_to_utc_time,
    normalize_timezone_name,
    utc_time_to_hhmm,
    utc_time_to_local_hhmm,
)
from pecha_api.accumulator.accumulator_models import Accumulator
from pecha_api.accumulator.accumulator_enums import AccumulatorType
from pecha_api.accumulator.accumulator_service import (
    resolve_accumulator_bookmark_mala_image_url,
)
from pecha_api.accumulator.group_accumulator_models import GroupAccumulator
from pecha_api.group_accumulator.group_accumulator_repository import (
    get_joined_group_accumulator_ids_by_user,
)
from pecha_api.mantra.mantra_repository import get_mantras_by_ids
from pecha_api.recitations.recitations_services import (
    build_first_segment_for_edition,
    get_first_segment_for_text,
)

logger = logging.getLogger(__name__)

from .routines_models import Routine, RoutineTimeBlock, RoutineSession
from .routines_enums import SessionType
from .routines_repository import (
    get_routine_by_user_id,
    get_routine_by_id_and_user,
    get_existing_collection_source_ids,
    get_existing_collection_source_ids_in_routine,
    get_collection_source_ids_by_time_block_id,
    time_block_exists_for_routine,
    get_time_block_by_id_and_routine,
    get_plan_source_ids_by_time_block_id,
    get_series_source_ids_by_time_block_id,
    get_plans_by_ids,
    get_time_block_by_routine_and_time,
    delete_sessions_by_time_block_id,
    save_routine,
    save_time_block,
    save_sessions,
    soft_delete_time_block,
    update_time_block as update_time_block_repo,
    get_time_blocks,
    get_sessions_by_time_block_ids,
    get_routine_series_and_recitation_counts,
)
from .response_message import (
    DUPLICATE_PLAN,
    DUPLICATE_SERIES,
    DUPLICATE_RECITATION_COLLECTION,
    DUPLICATE_GROUP_RECITATION_COLLECTION,
    DUPLICATE_ACCUMULATOR,
    DUPLICATE_GROUP_ACCUMULATOR,
    INVALID_TIME_FORMAT,
    INVALID_TIMER_DURATION,
    ROUTINE_ALREADY_EXISTS,
    ROUTINE_NOT_FOUND,
    SESSIONS_REQUIRED,
    SOURCE_ID_REQUIRED,
    TIME_ALREADY_EXISTS,
    TIME_BLOCK_NOT_FOUND,
    TIME_BLOCK_TIME_CONFLICT,
    NO_ROUTINE_CREATED_FOR_USER,
    SERIES_NOT_FOUND,
    PRESET_ACCUMULATOR_NOT_FOUND,
    ACCUMULATOR_ID_REQUIRED,
    GROUP_ACCUMULATOR_ID_REQUIRED,
    GROUP_ACCUMULATOR_NOT_FOUND,
    GROUP_ACCUMULATOR_NOT_JOINED,
)
from .routines_response_models import (
    SessionRequest,
    CreateTimeBlockRequest,
    UpdateTimeBlockRequest,
    SessionDTO,
    RoutineFirstSegmentDTO,
    TimeBlockDTO,
    RoutineWithTimeBlocksResponse,
    RoutineResponse,
    RoutineInfoResponse,
)


DEFAULT_ROUTINE_TIMEZONE = "UTC"


def _resolve_effective_timezone(
    timezone_name: Optional[str],
    routine: Optional[Routine] = None,
) -> str:
    normalized = normalize_timezone_name(timezone_name)
    if normalized is not None:
        return normalized
    if routine is not None and routine.timezone:
        return routine.timezone
    return DEFAULT_ROUTINE_TIMEZONE


def _sync_routine_timezone(
    routine: Routine,
    timezone_name: Optional[str],
) -> str:
    stored_timezone = normalize_timezone_name(timezone_name)
    if stored_timezone is not None:
        routine.timezone = stored_timezone
    return _resolve_effective_timezone(timezone_name, routine)


def _build_time_block_storage(
    *,
    local_time: str,
    timezone_name: str,
    time_int: Optional[int] = None,
) -> tuple[str, int, time]:
    resolved_time_int = time_int if time_int is not None else hhmm_to_time_int(local_time)
    time_utc = local_hhmm_to_utc_time(local_time, timezone_name)
    return local_time, resolved_time_int, time_utc


def _resolve_time_block_display(
    time_block: RoutineTimeBlock,
    routine_timezone: Optional[str],
) -> tuple[str, int]:
    time_utc = getattr(time_block, "time_utc", None)
    if time_utc is not None:
        if routine_timezone:
            local_hhmm = utc_time_to_local_hhmm(time_utc, routine_timezone)
        else:
            local_hhmm = utc_time_to_hhmm(time_utc)
        return local_hhmm, hhmm_to_time_int(local_hhmm)
    return time_block.time, time_block.time_int


def _time_block_dto(
    time_block: RoutineTimeBlock,
    *,
    effective_timezone: str,
    sessions: List[SessionDTO],
) -> TimeBlockDTO:
    display_time, display_time_int = _resolve_time_block_display(time_block, effective_timezone)
    return TimeBlockDTO(
        id=time_block.id,
        time=display_time,
        time_int=display_time_int,
        title=time_block.title,
        notification_enabled=time_block.notification_enabled,
        sessions=sessions,
    )


def _raise_unprocessable(message: str) -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=ResponseError(error=BAD_REQUEST, message=message).model_dump(),
    )


# Session types that report a type-specific message when source_id is missing;
# everything else falls back to SOURCE_ID_REQUIRED.
_MISSING_SOURCE_ID_MESSAGES = {
    SessionType.ACCUMULATOR: ACCUMULATOR_ID_REQUIRED,
    SessionType.GROUP_ACCUMULATOR: GROUP_ACCUMULATOR_ID_REQUIRED,
}


def _validate_session_source(session: SessionRequest) -> None:
    """TIMER sessions carry a positive duration_ms; every other type carries a
    source_id."""
    if session.session_type == SessionType.TIMER:
        if session.duration_ms is None or session.duration_ms <= 0:
            _raise_unprocessable(INVALID_TIMER_DURATION)
        return

    if session.source_id is None:
        _raise_unprocessable(
            _MISSING_SOURCE_ID_MESSAGES.get(session.session_type, SOURCE_ID_REQUIRED)
        )


def _validate_time_block_request(request: CreateTimeBlockRequest) -> None:
    # At least one session required
    if not request.sessions:
        _raise_unprocessable(SESSIONS_REQUIRED)

    # Time must be valid HH:MM 24-hour format
    if not TIME_FORMAT_PATTERN.match(request.time):
        _raise_unprocessable(INVALID_TIME_FORMAT)

    for session in request.sessions:
        _validate_session_source(session)

    _validate_session_uniqueness(request.sessions)


def _validate_session_uniqueness(sessions: List[SessionRequest]) -> None:
    plan_source_ids = [
        session.source_id
        for session in sessions
        if session.session_type == SessionType.PLAN
    ]
    if len(plan_source_ids) != len(set(plan_source_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ResponseError(
                error=BAD_REQUEST, message=DUPLICATE_PLAN
            ).model_dump(),
        )

    series_source_ids = [
        session.source_id
        for session in sessions
        if session.session_type == SessionType.SERIES
    ]
    if len(series_source_ids) != len(set(series_source_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ResponseError(
                error=BAD_REQUEST, message=DUPLICATE_SERIES
            ).model_dump(),
        )

    collection_source_ids = [
        session.source_id
        for session in sessions
        if session.session_type == SessionType.RECITATION_COLLECTION
    ]
    if len(collection_source_ids) != len(set(collection_source_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ResponseError(
                error=BAD_REQUEST, message=DUPLICATE_RECITATION_COLLECTION
            ).model_dump(),
        )

    group_collection_source_ids = [
        session.source_id
        for session in sessions
        if session.session_type == SessionType.GROUP_RECITATION_COLLECTION
    ]
    if len(group_collection_source_ids) != len(set(group_collection_source_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ResponseError(
                error=BAD_REQUEST, message=DUPLICATE_GROUP_RECITATION_COLLECTION
            ).model_dump(),
        )

    accumulator_source_ids = [
        session.source_id
        for session in sessions
        if session.session_type == SessionType.ACCUMULATOR
    ]
    if len(accumulator_source_ids) != len(set(accumulator_source_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ResponseError(
                error=BAD_REQUEST, message=DUPLICATE_ACCUMULATOR
            ).model_dump(),
        )

    group_accumulator_source_ids = [
        session.source_id
        for session in sessions
        if session.session_type == SessionType.GROUP_ACCUMULATOR
    ]
    if len(group_accumulator_source_ids) != len(set(group_accumulator_source_ids)):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=ResponseError(
                error=BAD_REQUEST, message=DUPLICATE_GROUP_ACCUMULATOR
            ).model_dump(),
        )


def _check_duplicate_collections(db, routine_id: UUID, sessions: List) -> None:
    """Check for duplicate recitation collections when adding a new time block."""
    for session_type, error_message in (
        (SessionType.RECITATION_COLLECTION, DUPLICATE_RECITATION_COLLECTION),
        (SessionType.GROUP_RECITATION_COLLECTION, DUPLICATE_GROUP_RECITATION_COLLECTION),
    ):
        existing_collection_ids = get_existing_collection_source_ids(
            db=db, routine_id=routine_id, session_type=session_type
        )
        new_collection_ids = [
            _as_uuid(s.source_id) for s in sessions if s.session_type == session_type
        ]
        overlap = set(new_collection_ids) & set(existing_collection_ids)
        if overlap:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=ResponseError(
                    error=BAD_REQUEST, message=error_message
                ).model_dump(),
            )


def _check_duplicate_collections_on_update(
    db, routine_id: UUID, time_block_id: UUID, sessions: List
) -> None:
    """Check for duplicate recitation collections when updating a time block."""
    for session_type, error_message in (
        (SessionType.RECITATION_COLLECTION, DUPLICATE_RECITATION_COLLECTION),
        (SessionType.GROUP_RECITATION_COLLECTION, DUPLICATE_GROUP_RECITATION_COLLECTION),
    ):
        existing_collection_ids = get_existing_collection_source_ids_in_routine(
            db=db,
            routine_id=routine_id,
            exclude_time_block_id=time_block_id,
            session_type=session_type,
        )
        new_collection_ids = [
            _as_uuid(s.source_id) for s in sessions if s.session_type == session_type
        ]
        overlap = set(new_collection_ids) & set(existing_collection_ids)
        if overlap:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=ResponseError(
                    error=BAD_REQUEST, message=error_message
                ).model_dump(),
            )


def _check_duplicate_time(db, routine_id: UUID, time: str) -> None:
    if time_block_exists_for_routine(db=db, routine_id=routine_id, time=time):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ResponseError(
                error=BAD_REQUEST, message=TIME_ALREADY_EXISTS
            ).model_dump(),
        )


def _extract_plan_ids(sessions: List) -> List[UUID]:
    return [_as_uuid(s.source_id) for s in sessions if s.session_type == SessionType.PLAN]


def _extract_series_ids(sessions: List) -> List[UUID]:
    return [_as_uuid(s.source_id) for s in sessions if s.session_type == SessionType.SERIES]


def _normalize_plan_sessions_to_series(db, sessions: List[SessionRequest]) -> List[SessionRequest]:
    plan_ids = [
        _as_uuid(session.source_id)
        for session in sessions
        if session.session_type == SessionType.PLAN and session.source_id is not None
    ]
    if not plan_ids:
        return sessions

    plans = get_plans_by_ids(db=db, plan_ids=plan_ids)
    plan_series_map = {
        plan.id: plan.series_id
        for plan in plans
        if getattr(plan, "series_id", None) is not None
    }
    if not plan_series_map:
        return sessions

    normalized: List[SessionRequest] = []
    for session in sessions:
        if (
            session.session_type == SessionType.PLAN
            and session.source_id is not None
            and _as_uuid(session.source_id) in plan_series_map
        ):
            normalized.append(
                SessionRequest(
                    session_type=SessionType.SERIES,
                    source_id=plan_series_map[_as_uuid(session.source_id)],
                    display_order=session.display_order,
                )
            )
        else:
            normalized.append(session)
    return normalized


def _validate_accumulators(db, sessions: List[SessionRequest]) -> None:
    raw_ids = [
        session.source_id
        for session in sessions
        if session.session_type == SessionType.ACCUMULATOR and session.source_id is not None
    ]
    if not raw_ids:
        return

    # source_id is a str (RECITATION sessions carry non-UUID pecha text ids),
    # so normalize both sides before comparing against the UUID column values.
    preset_ids = set()
    for raw_id in raw_ids:
        try:
            preset_ids.add(_as_uuid(raw_id))
        except (ValueError, AttributeError, TypeError):
            # A non-UUID source_id can never match a preset row.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error=BAD_REQUEST, message=PRESET_ACCUMULATOR_NOT_FOUND
                ).model_dump(),
            )

    found_ids = {
        _as_uuid(row.id)
        for row in db.query(Accumulator.id)
        .filter(
            Accumulator.id.in_(preset_ids),
            Accumulator.type == AccumulatorType.PRESET,
            Accumulator.deleted_at.is_(None),
        )
        .all()
    }
    if preset_ids - found_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ResponseError(
                error=BAD_REQUEST, message=PRESET_ACCUMULATOR_NOT_FOUND
            ).model_dump(),
        )


def _validate_group_accumulators(db, sessions: List[SessionRequest], user_id: UUID) -> None:
    """A GROUP_ACCUMULATOR session's source_id is a group_accumulators.id.

    The user must already have joined it: joining runs its own authorization
    (published group, join policy, private-group request flow) in
    join_group_accumulator_service, so the routine must not join on their
    behalf and silently bypass those gates.
    """
    raw_ids = [
        session.source_id
        for session in sessions
        if session.session_type == SessionType.GROUP_ACCUMULATOR
        and session.source_id is not None
    ]
    if not raw_ids:
        return

    group_accumulator_ids = set()
    for raw_id in raw_ids:
        try:
            group_accumulator_ids.add(_as_uuid(raw_id))
        except (ValueError, AttributeError, TypeError):
            # A non-UUID source_id can never match a group accumulator row.
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error=BAD_REQUEST, message=GROUP_ACCUMULATOR_NOT_FOUND
                ).model_dump(),
            )

    found_ids = {
        _as_uuid(row.id)
        for row in db.query(GroupAccumulator.id)
        .filter(
            GroupAccumulator.id.in_(group_accumulator_ids),
            GroupAccumulator.deleted_at.is_(None),
        )
        .all()
    }
    if group_accumulator_ids - found_ids:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ResponseError(
                error=BAD_REQUEST, message=GROUP_ACCUMULATOR_NOT_FOUND
            ).model_dump(),
        )

    joined_ids = {
        _as_uuid(joined_id)
        for joined_id in get_joined_group_accumulator_ids_by_user(
            db=db,
            user_id=user_id,
            group_accumulator_ids=list(group_accumulator_ids),
        )
    }
    if group_accumulator_ids - joined_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=ResponseError(
                error=BAD_REQUEST, message=GROUP_ACCUMULATOR_NOT_JOINED
            ).model_dump(),
        )


def _prepare_sessions(db, sessions: List[SessionRequest], user_id: UUID) -> List[SessionRequest]:
    sessions = _normalize_plan_sessions_to_series(db=db, sessions=sessions)
    _validate_session_uniqueness(sessions)
    _validate_accumulators(db=db, sessions=sessions)
    _validate_group_accumulators(db=db, sessions=sessions, user_id=user_id)
    return sessions


def _enroll_plans(db, user_id: UUID, plan_ids: List[UUID]) -> None:
    if not plan_ids:
        return

    already_enrolled = {
        row.plan_id
        for row in db.query(UserPlanProgress.plan_id)
        .filter(
            UserPlanProgress.user_id == user_id,
            UserPlanProgress.plan_id.in_(plan_ids),
        )
        .all()
    }

    for plan_id in plan_ids:
        if plan_id not in already_enrolled:
            new_progress = UserPlanProgress(
                user_id=user_id,
                plan_id=plan_id,
                streak_count=0,
                longest_streak=0,
                status=UserPlanStatus.NOT_STARTED,
                is_completed=False,
            )
            db.add(new_progress)

    try:
        db.commit()
    except IntegrityError:
        db.rollback()


def _enroll_series(db, user_id: UUID, series_ids: List[UUID]) -> None:
    if not series_ids:
        return

    from pecha_api.plans.plans_enums import SeriesStatus
    from pecha_api.plans.series.series_model import Series
    from pecha_api.plans.users.plan_users_models import UserSeriesEnrollment
    from pecha_api.plans.users.plan_user_series_repository import (
        get_user_series_enrollment_by_user_and_series,
        save_user_series_enrollment,
        get_first_plan_in_series,
    )
    from pecha_api.plans.users.plan_users_service import auto_enroll_in_next_plan

    for series_id in series_ids:
        series = (
            db.query(Series)
            .filter(Series.id == series_id, Series.deleted_at.is_(None))
            .first()
        )
        if not series:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error=BAD_REQUEST, message=SERIES_NOT_FOUND
                ).model_dump(),
            )

        existing_enrollment = get_user_series_enrollment_by_user_and_series(
            db=db, user_id=user_id, series_id=series_id
        )
        if existing_enrollment:
            continue

        first_plan = get_first_plan_in_series(db=db, series_id=series_id)
        enrollment = UserSeriesEnrollment(
            user_id=user_id,
            series_id=series_id,
            status=SeriesStatus.ACTIVE,
            auto_enroll_next=True,
            current_plan_id=first_plan.id if first_plan else None,
            enrolled_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            is_completed=False,
        )
        save_user_series_enrollment(db=db, enrollment=enrollment)

        if first_plan:
            auto_enroll_in_next_plan(
                db=db,
                user_id=user_id,
                plan_id=first_plan.id,
                series_enrollment_id=enrollment.id,
            )


def _enroll_new_sessions_on_update(
    db, user_id: UUID, time_block_id: UUID, new_sessions: List
) -> None:
    old_plan_ids = set(
        get_plan_source_ids_by_time_block_id(db=db, time_block_id=time_block_id)
    )
    new_plan_ids = set(_extract_plan_ids(new_sessions))
    _enroll_plans(db=db, user_id=user_id, plan_ids=list(new_plan_ids - old_plan_ids))

    old_series_ids = set(
        get_series_source_ids_by_time_block_id(db=db, time_block_id=time_block_id)
    )
    new_series_ids = set(_extract_series_ids(new_sessions))
    _enroll_series(db=db, user_id=user_id, series_ids=list(new_series_ids - old_series_ids))


def _validate_and_sync_update(
    db,
    user_id: UUID,
    routine_id: UUID,
    time_block_id: UUID,
    time: str,
    sessions: List[SessionRequest],
) -> None:
    existing_time_block = get_time_block_by_routine_and_time(
        db=db,
        routine_id=routine_id,
        time=time,
        exclude_time_block_id=time_block_id,
    )
    if existing_time_block:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=ResponseError(
                error=BAD_REQUEST, message=TIME_BLOCK_TIME_CONFLICT
            ).model_dump(),
        )

    _check_duplicate_collections_on_update(
        db=db,
        routine_id=routine_id,
        time_block_id=time_block_id,
        sessions=sessions,
    )

    _enroll_new_sessions_on_update(
        db=db,
        user_id=user_id,
        time_block_id=time_block_id,
        new_sessions=sessions,
    )


def build_session_models(time_block_id: UUID, sessions: List) -> List[RoutineSession]:
    return [
        RoutineSession(
            time_block_id=time_block_id,
            session_type=session.session_type,
            source_id=(
                str(session.source_id)
                if session.session_type != SessionType.TIMER and session.source_id is not None
                else None
            ),
            duration_ms=session.duration_ms if session.session_type == SessionType.TIMER else None,
            display_order=session.display_order,
        )
        for session in sessions
    ]


def _resolve_plan_sessions(db, plan_sessions: List[RoutineSession], user_id: UUID) -> List[SessionDTO]:
    if not plan_sessions:
        return []

    plan_ids = [_as_uuid(session.source_id) for session in plan_sessions]
    plans = get_plans_by_ids(db=db, plan_ids=plan_ids)
    plan_map = {plan.id: plan for plan in plans}

    # Fetch user progress data for all plan sessions
    progress_map = get_plan_progress_by_user_id_and_plan_ids(
        db=db, user_id=user_id, plan_ids=plan_ids
    )

    resolved = []
    for session in plan_sessions:
        plan_id = _as_uuid(session.source_id)
        plan = plan_map.get(plan_id)
        if plan is None:
            continue

        plan_image = safe_get_image_url(
            plan.image_url, resource_id=plan.id, resource_type="plan"
        )

        # Get user progress for this plan
        progress = progress_map.get(plan_id)
        
        resolved.append(
            SessionDTO(
                id=session.id,
                session_type=session.session_type,
                source_id=str(session.source_id) if session.source_id is not None else None,
                title=plan.title,
                language=(
                    plan.language.value
                    if hasattr(plan.language, "value")
                    else str(plan.language)
                ),
                image=plan_image,
                display_order=session.display_order,
                start_date=plan.start_date,  # Plan's start_date
                started_at=progress.started_at if progress else None,  # User's started_at
            )
        )
    return resolved


def _as_uuid(value) -> UUID:
    """RoutineSession.source_id is read back as a plain str, but tolerate an
    already-UUID value too (e.g. an in-memory session not yet round-tripped
    through the DB)."""
    return value if isinstance(value, UUID) else UUID(value)


async def _try_get_openpecha_text(text_id: str):
    try:
        return await get_text_by_id_from_openpecha(text_id=text_id)
    except HTTPException:
        return None


async def _try_get_first_segment_for_text(text_id: str):
    try:
        return await get_first_segment_for_text(text_id=text_id)
    except Exception:
        # A preview is a nice-to-have decoration; don't let a lookup failure
        # 500 the whole routine listing.
        logger.warning("Failed to build first segment preview for recitation text %s", text_id, exc_info=True)
        return None


async def _try_resolve_edition_text_id(source_id: str) -> Optional[str]:
    try:
        return await fetch_edition_text_id(edition_id=source_id)
    except Exception:
        return None


async def _try_build_first_segment_for_edition(edition_id: str):
    try:
        return await build_first_segment_for_edition(edition_id=edition_id)
    except Exception:
        logger.warning("Failed to build first segment preview for recitation edition %s", edition_id, exc_info=True)
        return None


async def _resolve_recitation_text_and_segment(source_id: str):
    """A RECITATION session's `source_id` is polymorphic: the recitations
    listing hands out OpenPecha edition ids labeled as `text_id` on the wire
    (see `_with_edition_id_as_text_id` in recitations_services.py), so it's
    usually an edition id rather than a plain text id. Try it as an edition
    id first, mirroring the resolution bookmark_utils.py already uses for
    chant bookmarks, and fall back to treating it as a text id.
    """
    edition_text_id = await _try_resolve_edition_text_id(source_id)
    if edition_text_id is not None:
        return await asyncio.gather(
            _try_get_openpecha_text(edition_text_id),
            _try_build_first_segment_for_edition(source_id),
        )
    return await asyncio.gather(
        _try_get_openpecha_text(source_id),
        _try_get_first_segment_for_text(source_id),
    )


async def _resolve_recitation_sessions(
    recitation_sessions: List[RoutineSession],
) -> List[SessionDTO]:
    if not recitation_sessions:
        return []

    text_ids = [str(session.source_id) for session in recitation_sessions]
    unique_text_ids = list(dict.fromkeys(text_ids))
    resolved_pairs = await asyncio.gather(
        *(_resolve_recitation_text_and_segment(text_id) for text_id in unique_text_ids)
    )
    text_map = {
        text_id: text
        for text_id, (text, _segment) in zip(unique_text_ids, resolved_pairs)
        if text is not None
    }
    previews_by_text_id = {
        text_id: (segment.id, segment.content)
        for text_id, (_text, segment) in zip(unique_text_ids, resolved_pairs)
        if segment is not None
    }

    resolved = []
    for session in recitation_sessions:
        text_id = str(session.source_id)
        text = text_map.get(text_id)
        if text is None:
            continue

        # A first-segment preview is a nice-to-have decoration (it depends on
        # OpenPecha having a critical edition/segmentation for this text); a
        # recitation session should still show up without one rather than
        # being dropped entirely.
        preview = previews_by_text_id.get(text_id)
        first_segment = None
        if preview is not None:
            first_segment_id, preview_content = preview
            first_segment = RoutineFirstSegmentDTO(
                id=first_segment_id,
                content=preview_content,
            )

        resolved.append(
            SessionDTO(
                id=session.id,
                session_type=session.session_type,
                source_id=text_id,
                title=text.title,
                language=text.language or "en",
                image=None,
                display_order=session.display_order,
                first_segment=first_segment,
            )
        )
    return resolved


def _resolve_timer_sessions(timer_sessions: List[RoutineSession]) -> List[SessionDTO]:
    return [
        SessionDTO(
            id=session.id,
            session_type=session.session_type,
            source_id=None,
            duration_ms=session.duration_ms,
            display_order=session.display_order,
        )
        for session in timer_sessions
    ]


def _resolve_recitation_collection_sessions(
    db, collection_sessions: List[RoutineSession], user_id: UUID
) -> List[SessionDTO]:
    """Resolve individual recitation collection sessions by fetching collection details."""
    if not collection_sessions:
        return []

    collection_ids = [_as_uuid(session.source_id) for session in collection_sessions]

    # Fetch collections owned by the user
    collections = (
        db.query(RecitationCollection)
        .filter(
            RecitationCollection.id.in_(collection_ids),
            RecitationCollection.user_id == user_id,
        )
        .all()
    )
    collection_map = {collection.id: collection for collection in collections}

    # Item counts come from the shared helper so soft-deleted items
    # (deleted_at set) are excluded, matching every other collection view.
    item_counts = get_recitation_collection_item_counts(
        db=db, collection_ids=collection_ids
    )

    resolved = []
    for session in collection_sessions:
        collection = collection_map.get(_as_uuid(session.source_id))
        if collection is None:
            continue
        
        # Generate presigned URL for collection image
        collection_image = safe_get_image_url(
            collection.img_url, resource_id=collection.id, resource_type="collection"
        )
        
        resolved.append(
            SessionDTO(
                id=session.id,
                session_type=session.session_type,
                source_id=str(session.source_id) if session.source_id is not None else None,
                title=collection.name,
                image=collection_image,
                display_order=session.display_order,
                item_count=item_counts.get(collection.id, 0),
            )
        )
    return resolved


def _resolve_group_recitation_collection_sessions(
    db, collection_sessions: List[RoutineSession]
) -> List[SessionDTO]:
    """Resolve group recitation collection sessions; source_id is the collection id."""
    if not collection_sessions:
        return []

    from sqlalchemy import func

    collection_ids = [_as_uuid(session.source_id) for session in collection_sessions]
    collections = (
        db.query(GroupRecitationCollection)
        .filter(
            GroupRecitationCollection.id.in_(collection_ids),
            GroupRecitationCollection.deleted_at.is_(None),
        )
        .all()
    )
    collection_map = {collection.id: collection for collection in collections}

    item_counts = dict(
        db.query(
            GroupRecitationCollectionItem.group_recitation_collection_id,
            func.count(GroupRecitationCollectionItem.id),
        )
        .filter(
            GroupRecitationCollectionItem.group_recitation_collection_id.in_(
                collection_ids
            ),
            GroupRecitationCollectionItem.deleted_at.is_(None),
        )
        .group_by(GroupRecitationCollectionItem.group_recitation_collection_id)
        .all()
    )

    resolved = []
    for session in collection_sessions:
        collection = collection_map.get(_as_uuid(session.source_id))
        if collection is None:
            continue

        collection_image = safe_get_image_url(
            collection.img_url,
            resource_id=collection.id,
            resource_type="collection",
        )
        resolved.append(
            SessionDTO(
                id=session.id,
                session_type=session.session_type,
                source_id=str(session.source_id) if session.source_id is not None else None,
                title=collection.name,
                image=collection_image,
                display_order=session.display_order,
                item_count=item_counts.get(collection.id, 0),
            )
        )
    return resolved


def _accumulator_mala_image(
    db, accumulator: Accumulator
) -> Optional[ImageUrlModel]:
    mala_image_url = resolve_accumulator_bookmark_mala_image_url(db, accumulator)
    if not mala_image_url:
        return None
    return ImageUrlModel(
        thumbnail=mala_image_url,
        medium=mala_image_url,
        original=mala_image_url,
    )


def _mantra_metadata_language(metadata) -> Optional[str]:
    if metadata is None:
        return None
    return (
        metadata.language.value
        if hasattr(metadata.language, "value")
        else str(metadata.language)
    )


def _select_mantra_metadata(metadata_entries, language: Optional[str]):
    if not metadata_entries:
        return None
    matched = filter_by_language_with_fallback(
        entries=list(metadata_entries),
        language=language,
        language_of=_mantra_metadata_language,
    )
    return matched[0] if matched else metadata_entries[0]


def _preset_session_title_and_language(
    mantra,
    language: Optional[str] = None,
) -> tuple[str, Optional[str]]:
    if mantra is not None and mantra.metadata_entries:
        mantra_metadata = _select_mantra_metadata(mantra.metadata_entries, language)
        if mantra_metadata and mantra_metadata.title:
            return (
                mantra_metadata.title,
                _mantra_metadata_language(mantra_metadata),
            )

    return "Untitled", None


def _resolve_accumulator_sessions(
    db,
    accumulator_sessions: List[RoutineSession],
    user_id: UUID,
    language: Optional[str] = None,
) -> List[SessionDTO]:
    if not accumulator_sessions:
        return []

    preset_ids = [_as_uuid(session.source_id) for session in accumulator_sessions]
    presets = (
        db.query(Accumulator)
        .filter(
            Accumulator.id.in_(preset_ids),
            Accumulator.type == AccumulatorType.PRESET,
            Accumulator.deleted_at.is_(None),
        )
        .all()
    )
    preset_map = {preset.id: preset for preset in presets}

    mantra_ids = [
        preset.mantra_id
        for preset in presets
        if preset.mantra_id is not None
    ]
    mantras_by_id = get_mantras_by_ids(db, mantra_ids)

    resolved = []
    for session in accumulator_sessions:
        preset_id = _as_uuid(session.source_id)
        preset = preset_map.get(preset_id)
        if preset is None:
            continue

        mantra = (
            mantras_by_id.get(preset.mantra_id)
            if preset.mantra_id is not None
            else None
        )
        title, session_language = _preset_session_title_and_language(
            mantra, language
        )
        resolved.append(
            SessionDTO(
                id=session.id,
                session_type=session.session_type,
                source_id=str(session.source_id) if session.source_id is not None else None,
                accumulator_id=preset_id,
                title=title,
                language=session_language,
                image=_accumulator_mala_image(db, preset),
                display_order=session.display_order,
            )
        )
    return resolved


def _resolve_group_accumulator_sessions(
    db,
    group_accumulator_sessions: List[RoutineSession],
) -> List[SessionDTO]:
    """Resolve group accumulator sessions; source_id is the group accumulator id."""
    if not group_accumulator_sessions:
        return []

    group_accumulator_ids = [
        _as_uuid(session.source_id) for session in group_accumulator_sessions
    ]
    group_accumulators = (
        db.query(GroupAccumulator)
        .filter(
            GroupAccumulator.id.in_(group_accumulator_ids),
            GroupAccumulator.deleted_at.is_(None),
        )
        .all()
    )
    group_accumulator_map = {
        group_accumulator.id: group_accumulator
        for group_accumulator in group_accumulators
    }

    resolved = []
    for session in group_accumulator_sessions:
        group_accumulator_id = _as_uuid(session.source_id)
        group_accumulator = group_accumulator_map.get(group_accumulator_id)
        if group_accumulator is None:
            continue

        resolved.append(
            SessionDTO(
                id=session.id,
                session_type=session.session_type,
                source_id=str(session.source_id) if session.source_id is not None else None,
                group_accumulator_id=group_accumulator_id,
                title=group_accumulator.title,
                image=get_image_url(group_accumulator.image_key),
                display_order=session.display_order,
            )
        )
    return resolved


def _series_metadata_language(metadata) -> Optional[str]:
    if metadata is None:
        return None
    return (
        metadata.language.value
        if hasattr(metadata.language, "value")
        else str(metadata.language)
    )


def _select_series_metadata(metadata_entries, language: Optional[str]):
    """Pick the metadata entry for ``language``, falling back to 'en', then first."""
    if not metadata_entries:
        return None
    matched = filter_by_language_with_fallback(
        entries=list(metadata_entries),
        language=language,
        language_of=_series_metadata_language,
    )
    return matched[0] if matched else metadata_entries[0]


def _plan_language(plan) -> str:
    return (
        plan.language.value
        if hasattr(plan.language, "value")
        else str(plan.language)
    )


def _filter_plans_by_language(plans: List, language: Optional[str]) -> List:
    if not plans:
        return []
    return filter_by_language_with_fallback(
        entries=list(plans),
        language=language,
        language_of=_plan_language,
    )


def _build_series_session_dto(
    session, series, first_plan, progress, current_plan, language: Optional[str] = None
) -> SessionDTO:
    metadata = _select_series_metadata(series.metadata_entries, language)
    series_image = safe_get_image_url(
        series.image, resource_id=series.id, resource_type="series"
    )
    return SessionDTO(
        id=session.id,
        session_type=session.session_type,
        source_id=str(session.source_id) if session.source_id is not None else None,
        title=metadata.title if metadata else "Untitled Series",
        language=_series_metadata_language(metadata),
        image=series_image,
        display_order=session.display_order,
        start_date=first_plan.start_date if first_plan else None,  # First plan's start_date
        started_at=progress.started_at if progress else None,  # User's started_at for first plan
        current_plan_id=current_plan.id if current_plan else None,
        current_plan_title=current_plan.title if current_plan else None,
    )


def _resolve_series_sessions(
    db, series_sessions: List[RoutineSession], user_id: UUID, language: Optional[str] = None
) -> List[SessionDTO]:
    if not series_sessions:
        return []

    from pecha_api.plans.public.plan_service import _resolve_plan_for_date_in_series
    from pecha_api.plans.series.series_repository import get_series_by_ids
    from pecha_api.plans.users.plan_user_series_repository import get_plans_by_series_ids

    series_ids = [_as_uuid(session.source_id) for session in series_sessions]
    series_list = get_series_by_ids(db=db, series_ids=series_ids)
    series_map = {series.id: series for series in series_list}

    plans_by_series = get_plans_by_series_ids(db=db, series_ids=series_ids)
    today = datetime.now(timezone.utc).date()
    language_plans_by_series = {
        series_id: _filter_plans_by_language(plans, language)
        for series_id, plans in plans_by_series.items()
    }
    current_plan_map = {
        series_id: _resolve_plan_for_date_in_series(language_plans, today)
        for series_id, language_plans in language_plans_by_series.items()
    }
    first_plan_map = {
        series_id: language_plans[0] if language_plans else None
        for series_id, language_plans in language_plans_by_series.items()
    }
    first_plan_ids = [plan.id for plan in first_plan_map.values() if plan is not None]
    progress_map = get_plan_progress_by_user_id_and_plan_ids(
        db=db, user_id=user_id, plan_ids=first_plan_ids
    )

    resolved = []
    for session in series_sessions:
        series_id = _as_uuid(session.source_id)
        series = series_map.get(series_id)
        if series is None:
            continue

        first_plan = first_plan_map.get(series_id)
        progress = progress_map.get(first_plan.id) if first_plan else None
        current_plan = current_plan_map.get(series_id)
        resolved.append(
            _build_series_session_dto(
                session, series, first_plan, progress, current_plan, language=language
            )
        )
    return resolved


async def _resolve_sessions(db, sessions: List[RoutineSession], user_id: UUID, language: Optional[str] = None) -> List[SessionDTO]:
    plan_sessions = [
        session for session in sessions if session.session_type == SessionType.PLAN
    ]
    series_sessions = [
        session for session in sessions if session.session_type == SessionType.SERIES
    ]
    recitation_sessions = [
        session
        for session in sessions
        if session.session_type == SessionType.RECITATION
    ]
    recitation_collection_sessions = [
        session
        for session in sessions
        if session.session_type == SessionType.RECITATION_COLLECTION
    ]
    group_recitation_collection_sessions = [
        session
        for session in sessions
        if session.session_type == SessionType.GROUP_RECITATION_COLLECTION
    ]
    timer_sessions = [
        session for session in sessions if session.session_type == SessionType.TIMER
    ]
    accumulator_sessions = [
        session
        for session in sessions
        if session.session_type == SessionType.ACCUMULATOR
    ]
    group_accumulator_sessions = [
        session
        for session in sessions
        if session.session_type == SessionType.GROUP_ACCUMULATOR
    ]

    resolved_plans = _resolve_plan_sessions(db=db, plan_sessions=plan_sessions, user_id=user_id)
    resolved_series = _resolve_series_sessions(db=db, series_sessions=series_sessions, user_id=user_id, language=language)
    resolved_recitations = await _resolve_recitation_sessions(
        recitation_sessions=recitation_sessions
    )
    resolved_collections = _resolve_recitation_collection_sessions(
        db=db, collection_sessions=recitation_collection_sessions, user_id=user_id
    )
    resolved_group_collections = _resolve_group_recitation_collection_sessions(
        db=db, collection_sessions=group_recitation_collection_sessions
    )
    resolved_timers = _resolve_timer_sessions(timer_sessions=timer_sessions)
    resolved_accumulators = _resolve_accumulator_sessions(
        db=db,
        accumulator_sessions=accumulator_sessions,
        user_id=user_id,
        language=language,
    )
    resolved_group_accumulators = _resolve_group_accumulator_sessions(
        db=db,
        group_accumulator_sessions=group_accumulator_sessions,
    )

    resolved = (
        resolved_plans
        + resolved_series
        + resolved_recitations
        + resolved_collections
        + resolved_group_collections
        + resolved_timers
        + resolved_accumulators
        + resolved_group_accumulators
    )
    resolved.sort(key=lambda session: session.display_order)

    return resolved


def group_sessions_by_block(
    sessions: List[RoutineSession],
) -> Dict[UUID, List[RoutineSession]]:
    sessions_by_block: Dict[UUID, List[RoutineSession]] = {}
    for session in sessions:
        if session.time_block_id not in sessions_by_block:
            sessions_by_block[session.time_block_id] = []
        sessions_by_block[session.time_block_id].append(session)
    return sessions_by_block


async def build_time_block_dto(
    db,
    time_block: RoutineTimeBlock,
    sessions: List[RoutineSession],
    user_id: UUID,
    language: Optional[str] = None,
    routine_timezone: Optional[str] = None,
) -> TimeBlockDTO:
    resolved_sessions = await _resolve_sessions(db=db, sessions=sessions, user_id=user_id, language=language)
    display_time, display_time_int = _resolve_time_block_display(time_block, routine_timezone)
    return TimeBlockDTO(
        id=time_block.id,
        time=display_time,
        time_int=display_time_int,
        title=time_block.title,
        notification_enabled=time_block.notification_enabled,
        sessions=resolved_sessions,
    )


async def create_routine_with_time_block(
    token: str, request: CreateTimeBlockRequest, timezone_name: Optional[str] = None
) -> RoutineWithTimeBlocksResponse:

    current_user = validate_and_extract_user_details(token=token)
    _validate_time_block_request(request)
    stored_timezone = normalize_timezone_name(timezone_name)
    effective_timezone = _resolve_effective_timezone(timezone_name)

    with SessionLocal() as db:
        prepared_sessions = _prepare_sessions(
            db=db, sessions=request.sessions, user_id=current_user.id
        )

        # Check routine doesn't already exist (business rule: exclude soft-deleted)
        existing_routine = get_routine_by_user_id(
            db=db, user_id=current_user.id, include_deleted=False
        )
        if existing_routine:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ResponseError(
                    error=BAD_REQUEST, message=ROUTINE_ALREADY_EXISTS
                ).model_dump(),
            )

        local_time, time_int, time_utc = _build_time_block_storage(
            local_time=request.time,
            timezone_name=effective_timezone,
            time_int=request.time_int,
        )
        # Create routine
        routine = Routine(user_id=current_user.id, timezone=stored_timezone)
        saved_routine = save_routine(db=db, routine=routine)

        # Create time block
        time_block = RoutineTimeBlock(
            routine_id=saved_routine.id,
            time=local_time,
            time_utc=time_utc,
            time_int=time_int,
            title=request.title,
            notification_enabled=request.notification_enabled,
        )
        saved_time_block = save_time_block(db=db, time_block=time_block)
        session_models = build_session_models(
            time_block_id=saved_time_block.id, sessions=prepared_sessions
        )
        saved_sessions = save_sessions(db=db, sessions=session_models)
        _enroll_plans(
            db=db, user_id=current_user.id, plan_ids=_extract_plan_ids(prepared_sessions)
        )
        _enroll_series(
            db=db, user_id=current_user.id, series_ids=_extract_series_ids(prepared_sessions)
        )

        time_block_dto = await build_time_block_dto(
            db=db,
            time_block=saved_time_block,
            sessions=saved_sessions,
            user_id=current_user.id,
            routine_timezone=stored_timezone,
        )

        return RoutineWithTimeBlocksResponse(
            id=saved_routine.id,
            time_blocks=[time_block_dto],
        )


async def get_user_routine(
    token: str, skip: int = 0, limit: int = 20, language: Optional[str] = None
) -> RoutineResponse:

    current_user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        routine = get_routine_by_user_id(
            db=db, user_id=current_user.id, include_deleted=False
        )

        if routine is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ResponseError(
                    error=BAD_REQUEST, message=NO_ROUTINE_CREATED_FOR_USER
                ).model_dump(),
            )
        time_blocks, total = get_time_blocks(
            db=db,
            routine_id=routine.id,
            include_deleted=False,
            order_by_field=RoutineTimeBlock.time_int,
            order_desc=False,
            skip=skip,
            limit=limit,
        )

        if not time_blocks:
            return RoutineResponse(
                id=routine.id, time_blocks=[], skip=skip, limit=limit, total=total
            )
        time_block_ids = [tb.id for tb in time_blocks]
        all_sessions = get_sessions_by_time_block_ids(
            db=db,
            time_block_ids=time_block_ids,
            order_by_field=RoutineSession.display_order,
            order_desc=False,
        )
        sessions_by_block = group_sessions_by_block(all_sessions)
        time_block_dtos = [
            await build_time_block_dto(
                db=db,
                time_block=tb,
                sessions=sessions_by_block.get(tb.id, []),
                user_id=current_user.id,
                language=language,
                routine_timezone=routine.timezone,
            )
            for tb in time_blocks
        ]
        return RoutineResponse(
            id=routine.id,
            time_blocks=time_block_dtos,
            skip=skip,
            limit=limit,
            total=total,
        )


async def get_user_routine_info(token: str) -> RoutineInfoResponse:
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        routine = get_routine_by_user_id(
            db=db, user_id=current_user.id, include_deleted=False
        )

        if routine is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ResponseError(
                    error=BAD_REQUEST, message=NO_ROUTINE_CREATED_FOR_USER
                ).model_dump(),
            )

        series_count, recitation_count = get_routine_series_and_recitation_counts(
            db=db, routine_id=routine.id
        )

        return RoutineInfoResponse(
            series_count=series_count,
            recitation_count=recitation_count,
        )


async def add_time_block_to_routine(
    token: str, routine_id: UUID, request: CreateTimeBlockRequest, timezone_name: Optional[str] = None
) -> TimeBlockDTO:

    current_user = validate_and_extract_user_details(token=token)

    _validate_time_block_request(request)

    with SessionLocal() as db:
        # Check routine exists and belongs to user
        routine = get_routine_by_id_and_user(
            db=db, routine_id=routine_id, user_id=current_user.id
        )
        if not routine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error=BAD_REQUEST, message=ROUTINE_NOT_FOUND
                ).model_dump(),
            )

        effective_timezone = _sync_routine_timezone(routine, timezone_name)

        local_time, time_int, time_utc = _build_time_block_storage(
            local_time=request.time,
            timezone_name=effective_timezone,
            time_int=request.time_int,
        )

        _check_duplicate_collections(db=db, routine_id=routine_id, sessions=request.sessions)
        _check_duplicate_time(db=db, routine_id=routine_id, time=local_time)

        prepared_sessions = _prepare_sessions(
            db=db, sessions=request.sessions, user_id=current_user.id
        )

        # Save time block
        time_block = RoutineTimeBlock(
            routine_id=routine_id,
            time=local_time,
            time_utc=time_utc,
            time_int=time_int,
            title=request.title,
            notification_enabled=request.notification_enabled,
        )
        saved_time_block = save_time_block(db=db, time_block=time_block)

        session_models = build_session_models(
            time_block_id=saved_time_block.id, sessions=prepared_sessions
        )
        saved_sessions = save_sessions(db=db, sessions=session_models)

        _enroll_plans(
            db=db, user_id=current_user.id, plan_ids=_extract_plan_ids(prepared_sessions)
        )
        _enroll_series(
            db=db, user_id=current_user.id, series_ids=_extract_series_ids(prepared_sessions)
        )

        resolved_sessions = await _resolve_sessions(db=db, sessions=saved_sessions, user_id=current_user.id)
        return _time_block_dto(
            saved_time_block,
            effective_timezone=effective_timezone,
            sessions=resolved_sessions,
        )


def delete_time_block(token: str, routine_id: UUID, time_block_id: UUID) -> None:

    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        routine = get_routine_by_id_and_user(
            db=db, routine_id=routine_id, user_id=current_user.id
        )
        if not routine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error=BAD_REQUEST, message=ROUTINE_NOT_FOUND
                ).model_dump(),
            )

        # Find the time block
        time_block = get_time_block_by_id_and_routine(
            db=db, time_block_id=time_block_id, routine_id=routine_id
        )
        if not time_block:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error=BAD_REQUEST, message=TIME_BLOCK_NOT_FOUND
                ).model_dump(),
            )

        soft_delete_time_block(db=db, time_block=time_block)


async def update_time_block_service(
    token: str,
    routine_id: UUID,
    time_block_id: UUID,
    request: UpdateTimeBlockRequest,
    timezone_name: Optional[str] = None,
) -> TimeBlockDTO:

    current_user = validate_and_extract_user_details(token=token)

    _validate_time_block_request(request)

    with SessionLocal() as db:
        routine = get_routine_by_id_and_user(
            db=db, routine_id=routine_id, user_id=current_user.id
        )
        if not routine:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error=BAD_REQUEST, message=ROUTINE_NOT_FOUND
                ).model_dump(),
            )

        effective_timezone = _sync_routine_timezone(routine, timezone_name)

        local_time, time_int, time_utc = _build_time_block_storage(
            local_time=request.time,
            timezone_name=effective_timezone,
            time_int=request.time_int,
        )

        time_block = get_time_block_by_id_and_routine(
            db=db, time_block_id=time_block_id, routine_id=routine_id
        )
        if not time_block:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error=BAD_REQUEST, message=TIME_BLOCK_NOT_FOUND
                ).model_dump(),
            )

        prepared_sessions = _prepare_sessions(
            db=db, sessions=request.sessions, user_id=current_user.id
        )

        _validate_and_sync_update(
            db=db,
            user_id=current_user.id,
            routine_id=routine_id,
            time_block_id=time_block_id,
            time=local_time,
            sessions=prepared_sessions,
        )

        delete_sessions_by_time_block_id(db=db, time_block_id=time_block_id)

        updated_time_block = update_time_block_repo(
            db=db,
            time_block=time_block,
            time=local_time,
            time_utc=time_utc,
            time_int=time_int,
            title=request.title,
            notification_enabled=request.notification_enabled,
        )

        session_models = build_session_models(
            time_block_id=updated_time_block.id, sessions=prepared_sessions
        )
        saved_sessions = save_sessions(db=db, sessions=session_models)

        resolved_sessions = await _resolve_sessions(db=db, sessions=saved_sessions, user_id=current_user.id)
        return _time_block_dto(
            updated_time_block,
            effective_timezone=effective_timezone,
            sessions=resolved_sessions,
        )
