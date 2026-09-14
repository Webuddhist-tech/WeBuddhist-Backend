import asyncio
from typing import Optional
from uuid import UUID
from datetime import datetime, timezone
from fastapi import HTTPException
from starlette import status
from typing import List
from typing import Set
from pecha_api.config import get
from pecha_api.plans.shared.subtask_content_resolver import resolve_subtasks_content

from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_models import PlanSubTask

from pecha_api.error_contants import ErrorConstants
from pecha_api.plans.plans_enums import UserPlanStatus, EnrollmentSource, SeriesStatus
from pecha_api.plans.shared.utils import load_plans_from_json, convert_plan_model_to_dto
from pecha_api.plans.users.plan_users_models import UserPlanProgress, UserSubTaskCompletion, UserTaskCompletion, UserDayCompletion, UserSeriesEnrollment
from pecha_api.plans.series.series_model import Series
from pecha_api.plans.users.plan_users_response_models import (
    UserPlanDayCompletionStatus,
    UserPlanDayCompletionStatusResponse,
    UserPlanEnrollRequest, 
    UserPlanDayDetailsResponse, 
    UserTaskDTO, 
    UserSubTaskDTO,
    UserPlansResponse,
    UserPlanDTO,
    UserPlanProgressResponse,
    UserSeriesEnrollRequest,
    UserSeriesEnrollmentDTO,
    UserSeriesEnrollmentsResponse,
    UserSeriesProgressResponse,
    UpdateSeriesEnrollmentRequest,
    UserSeriesDaysCompletedDTO,
    UserSeriesDaysCompletedResponse,
)


from pecha_api.plans.tasks.plan_tasks_repository import get_task_by_id, get_tasks_by_plan_item_id
from pecha_api.plans.users.plan_user_task_repository import delete_user_task_completion, save_user_task_completion, get_user_task_completions_by_user_id_and_task_ids, get_uncompleted_user_task_ids
from pecha_api.plans.users.plan_users_subtasks_repository import (
    save_user_sub_task_completions, 
    get_user_subtask_completions_by_user_id_and_sub_task_ids, 
    save_user_sub_task_completions_bulk, 
    get_uncompleted_user_sub_task_ids,
    get_user_sub_task_by_user_id_and_sub_task_id
)

from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.plans.authors.plan_authors_service import safe_get_image_url
from pecha_api.plans.plans_enums import ContentType

from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_repository import get_sub_task_by_subtask_id, get_sub_tasks_by_task_id

from pecha_api.users.users_service import validate_and_extract_user_details
from pecha_api.db.database import SessionLocal
from pecha_api.plans.cms.cms_plans_repository import get_plan_by_id
from pecha_api.plans.tags.tag_helpers import tags_to_summary_dtos
from pecha_api.plans.auth.plan_auth_models import ResponseError

from pecha_api.plans.items.plan_items_repository import get_days_by_plan_id, get_plan_day_with_tasks_and_subtasks, get_plan_item_by_id
from pecha_api.plans.response_message import (
    ALREADY_COMPLETED_SUB_TASK, 
    BAD_REQUEST, PLAN_NOT_FOUND, 
    ALREADY_ENROLLED_IN_PLAN, 
    SUB_TASK_NOT_FOUND, 
    TASK_NOT_FOUND, 
    SUB_TASKS_NOT_COMPLETED
)
from pecha_api.plans.tasks.plan_tasks_models import PlanTask
from pecha_api.plans.users.plan_user_day_repository import get_completed_day_ids_by_user_id_and_day_ids, save_user_day_completion, delete_user_day_completion, get_user_day_completion_by_user_id_and_day_id
from pecha_api.daily_log.daily_log_cache_service import schedule_invalidate_user_stats_cache
from pecha_api.plans.users.plan_user_series_day_sync_service import sync_series_day_completion
from pecha_api.plans.users.plan_users_subtasks_repository import (
    save_user_sub_task_completions, 
    get_user_subtask_completions_by_user_id_and_sub_task_ids, 
    save_user_sub_task_completions_bulk, delete_user_subtask_completion,
)

from pecha_api.plans.users.plan_users_progress_repository import (
    get_plan_progress_by_user_id_and_plan_id,
    get_plan_progress_by_user_id_and_plan_ids,
    save_plan_progress,
    get_user_enrolled_plans_with_details,
    delete_user_plan_progress,
    get_user_series_days_completed_paginated,
    count_user_completed_days_for_plan_ids,
    get_user_completed_days_count_by_series_ids,
)
from pecha_api.plans.users.plan_user_series_repository import (
    get_user_series_enrollment_by_user_and_series,
    get_next_plan_in_series,
    update_current_plan_in_series,
    mark_series_enrollment_completed,
    is_series_completed_for_user,
    save_user_series_enrollment,
    get_user_series_enrollments_by_user_id,
    delete_user_series_enrollment,
    update_user_series_enrollment,
    get_first_plan_in_series,
    get_plans_by_series_id,
    get_plans_by_series_ids,
    get_paginated_plans_from_enrolled_series,
    get_series_partner,
    get_group_ids_by_series_partner_ids,
)
from pecha_api.plans.series.series_repository import (
    get_series_by_ids,
    get_plans_by_ids,
    get_enrolled_count_map_by_series_ids,
)
from pecha_api.plans.shared.metadata_utils import filter_by_language_with_fallback
from pecha_api.plans.groups.groups_repository import (
    get_group_ids_by_plan_ids,
    get_group_ids_by_series_ids,
    get_user_series_enrollment_partner_map,
    upsert_group_join,
)
from pecha_api.plans.groups.groups_service import get_group_summaries_by_ids
from pecha_api.plans.groups.group_summary_models import AuthorGroupSummaryDTO
from pecha_api.plans.series.series_service import (
    build_series_partner_dto,
    get_language_filtered_series_plan_ids,
)
from pecha_api.plans.users.series_user_progress import (
    load_series_partner_context,
    resolve_series_group_for_user,
    series_progress_from_plans,
)
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.config import get
import logging

logger = logging.getLogger(__name__)


def _resolve_plan_group_id(
    plan,
    plan_group_ids: dict[UUID, UUID],
    series_group_ids: dict[UUID, UUID],
) -> Optional[UUID]:
    plan_group_id = plan_group_ids.get(plan.id)
    if plan_group_id:
        return plan_group_id
    series_id = getattr(plan, "series_id", None)
    if series_id:
        return series_group_ids.get(series_id)
    return None


def _group_summary_for_id(
    group_id: Optional[UUID],
    group_summaries: dict[UUID, AuthorGroupSummaryDTO],
) -> Optional[AuthorGroupSummaryDTO]:
    if not group_id:
        return None
    group_summary = group_summaries.get(group_id)
    if not group_summary:
        return None
    return AuthorGroupSummaryDTO.model_validate(group_summary.model_dump())


def _series_progress_from_plans(
    plans: list,
    language: Optional[str] = None,
    *,
    completed_day_count: int = 0,
):
    return series_progress_from_plans(
        plans=plans,
        language=language,
        completed_day_count=completed_day_count,
    )


def _load_series_partner_context(
    db,
    user_id: UUID,
    series_ids: list[UUID],
    *,
    language: Optional[str] = None,
):
    return load_series_partner_context(
        db=db,
        user_id=user_id,
        series_ids=series_ids,
        language=language,
    )


def _resolve_series_group_for_user(
    series_id: UUID,
    *,
    series_group_ids: dict[UUID, UUID],
    group_summaries: dict[UUID, AuthorGroupSummaryDTO],
    partner_group_by_series: dict[UUID, Optional[AuthorGroupSummaryDTO]],
    enrollment_partner_map: dict[UUID, Optional[UUID]],
) -> Optional[AuthorGroupSummaryDTO]:
    return resolve_series_group_for_user(
        series_id,
        series_group_ids=series_group_ids,
        group_summaries=group_summaries,
        partner_group_by_series=partner_group_by_series,
        enrollment_partner_map=enrollment_partner_map,
        group_summary_for_id=_group_summary_for_id,
    )


def _load_group_summaries_for_plans(
    db,
    plans: list,
    *,
    extra_series_ids: Optional[list[UUID]] = None,
    language: Optional[str] = None,
) -> tuple[dict[UUID, AuthorGroupSummaryDTO], dict[UUID, UUID], dict[UUID, UUID]]:
    if not plans and not extra_series_ids:
        return {}, {}, {}
    plan_ids = [plan.id for plan in plans]
    series_ids = list({getattr(plan, "series_id", None) for plan in plans if getattr(plan, "series_id", None)})
    if extra_series_ids:
        series_ids = list(dict.fromkeys(series_ids + extra_series_ids))
    plan_group_ids = get_group_ids_by_plan_ids(db=db, plan_ids=plan_ids)
    series_group_ids = get_group_ids_by_series_ids(db=db, series_ids=series_ids)
    all_group_ids = list(set(plan_group_ids.values()) | set(series_group_ids.values()))
    return get_group_summaries_by_ids(db=db, group_ids=all_group_ids, language=language), plan_group_ids, series_group_ids

# Helper functions for enrollment checking

def is_user_enrolled_in_plan(db: SessionLocal, user_id: UUID, plan_id: UUID) -> bool:
    """Check if user is enrolled in a plan (either directly or through series enrollment)"""
    # Check direct enrollment
    direct_enrollment = get_plan_progress_by_user_id_and_plan_id(db, user_id, plan_id)
    if direct_enrollment:
        return True
    
    # Check virtual enrollment through series
    plan = get_plan_by_id(db, plan_id)
    if plan and plan.series_id:
        series_enrollment = get_user_series_enrollment_by_user_and_series(db, user_id, plan.series_id)
        return series_enrollment is not None
    
    return False


def get_or_create_plan_progress(db: SessionLocal, user_id: UUID, plan_id: UUID) -> Optional[UserPlanProgress]:
    """Get existing plan progress or create virtual one for series-enrolled users"""
    # Check for existing direct enrollment
    existing_progress = get_plan_progress_by_user_id_and_plan_id(db, user_id, plan_id)
    if existing_progress:
        return existing_progress
    
    # Check for series enrollment and create virtual progress if needed
    plan = get_plan_by_id(db, plan_id)
    if plan and plan.series_id:
        series_enrollment = get_user_series_enrollment_by_user_and_series(db, user_id, plan.series_id)
        if series_enrollment:
            # Create progress record for series-enrolled user
            new_progress = UserPlanProgress(
                user_id=user_id,
                plan_id=plan_id,
                enrollment_source=EnrollmentSource.SERIES,
                series_enrollment_id=series_enrollment.id,
                auto_enrolled=True,
                auto_enrolled_at=datetime.now(timezone.utc),
                status=UserPlanStatus.NOT_STARTED,
                started_at=datetime.now(timezone.utc),
                created_at=datetime.now(timezone.utc),
                is_completed=False,
            )
            return save_plan_progress(db, new_progress)
    
    return None


def handle_plan_completion_and_series_progression(db: SessionLocal, user_id: UUID, completed_plan_id: UUID):
    """Handle plan completion and check for series auto-progression"""
    # Mark plan as completed (this should be called from existing completion logic)
    plan_progress = get_plan_progress_by_user_id_and_plan_id(db, user_id, completed_plan_id)
    if not plan_progress:
        return

    if plan_progress.is_completed:
        return

    # Mark plan progress as completed
    plan_progress.is_completed = True
    plan_progress.completed_at = datetime.now(timezone.utc)
    plan_progress.status = UserPlanStatus.COMPLETED
    save_plan_progress(db, plan_progress)
    
    # Check if this was part of a series enrollment
    if plan_progress.series_enrollment_id:
        series_enrollment = db.query(UserSeriesEnrollment).filter(
            UserSeriesEnrollment.id == plan_progress.series_enrollment_id
        ).first()
        
        if series_enrollment and series_enrollment.auto_enroll_next:
            # Find next plan in series
            next_plan = get_next_plan_in_series(db, series_enrollment.series_id, completed_plan_id)
            
            if next_plan:
                # Auto-enroll in next plan
                auto_enroll_in_next_plan(db, user_id, next_plan.id, series_enrollment.id)
                # Update current plan in series enrollment
                update_current_plan_in_series(db, user_id, series_enrollment.series_id, next_plan.id)
            else:
                # No more plans - mark series as completed
                if is_series_completed_for_user(db, user_id, series_enrollment.series_id):
                    mark_series_enrollment_completed(db, user_id, series_enrollment.series_id)


def auto_enroll_in_next_plan(db: SessionLocal, user_id: UUID, plan_id: UUID, series_enrollment_id: UUID):
    """Auto-enrolls user in next plan of a series"""
    # Check if already has progress record (avoid duplicates)
    existing_progress = get_plan_progress_by_user_id_and_plan_id(db, user_id, plan_id)
    if existing_progress:
        return existing_progress
    
    # Create progress record for next plan
    new_progress = UserPlanProgress(
        user_id=user_id,
        plan_id=plan_id,
        enrollment_source=EnrollmentSource.SERIES,
        series_enrollment_id=series_enrollment_id,
        auto_enrolled=True,
        auto_enrolled_at=datetime.now(timezone.utc),
        status=UserPlanStatus.NOT_STARTED,
        started_at=datetime.now(timezone.utc),
        created_at=datetime.now(timezone.utc),
        is_completed=False,
    )
    return save_plan_progress(db, new_progress)


async def get_user_enrolled_plans(
    token: str,
    status_filter: Optional[str] = None,
    series_id: Optional[UUID] = None,
    language: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> UserPlansResponse:

    from sqlalchemy import func
    from pecha_api.plans.items.plan_items_models import PlanItem
    
    current_user = validate_and_extract_user_details(token=token)
    
    normalized_status = status_filter.upper() if status_filter else None
    
    with SessionLocal() as db:
        plans, total = get_paginated_plans_from_enrolled_series(
            db=db,
            user_id=current_user.id,
            status_filter=normalized_status,
            series_id=series_id,
            language=language,
            skip=skip,
            limit=limit,
        )
        
        if not plans:
            return UserPlansResponse(
                plans=[],
                skip=skip,
                limit=limit,
                total=total
            )
        
        plan_ids = [plan.id for plan in plans]
        
        days_count_query = (
            db.query(PlanItem.plan_id, func.count(PlanItem.id).label('total_days'))
            .filter(PlanItem.plan_id.in_(plan_ids))
            .group_by(PlanItem.plan_id)
            .all()
        )
        days_count_map = {row.plan_id: row.total_days for row in days_count_query}
        
        progress_map = get_plan_progress_by_user_id_and_plan_ids(db, current_user.id, plan_ids)
        group_summaries, plan_group_ids, series_group_ids = _load_group_summaries_for_plans(
            db, plans, language=language
        )
        
        enrolled_plans = []
        
        for plan in plans:
            progress = progress_map.get(plan.id)
            started_at = progress.started_at if progress else None
            plan_group_id = _resolve_plan_group_id(plan, plan_group_ids, series_group_ids)
            
            user_plan = UserPlanDTO(
                id=plan.id,
                title=plan.title,
                description=plan.description or "",
                language=plan.language.value if hasattr(plan.language, 'value') else str(plan.language),
                difficulty_level=plan.difficulty_level.value if hasattr(plan.difficulty_level, 'value') else str(plan.difficulty_level),
                image=safe_get_image_url(plan.image_url, resource_id=plan.id, resource_type="plan"),
                started_at=started_at,
                total_days=days_count_map.get(plan.id, 0),
                tags=tags_to_summary_dtos(plan.tag_list),
                start_date=plan.start_date,
                display_order=plan.display_order,
                group=_group_summary_for_id(plan_group_id, group_summaries),
            )
            enrolled_plans.append(user_plan)
        
        return UserPlansResponse(
            plans=enrolled_plans,
            skip=skip,
            limit=limit,
            total=total
        )


def enroll_user_in_plan(token: str, enroll_request: UserPlanEnrollRequest) -> None:
    """Enroll user in a plan (direct enrollment)"""
    current_user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        plan_model = get_plan_by_id(db=db, plan_id=enroll_request.plan_id)
        if not plan_model:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(error=BAD_REQUEST, message=PLAN_NOT_FOUND).model_dump()
            )
        
        # Check if user is already enrolled (either directly or through series)
        if is_user_enrolled_in_plan(db, current_user.id, enroll_request.plan_id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ResponseError(error=BAD_REQUEST, message=ALREADY_ENROLLED_IN_PLAN).model_dump()
            )

        new_progress = UserPlanProgress(
            user_id=current_user.id,
            plan_id=plan_model.id,
            enrollment_source=EnrollmentSource.DIRECT,  # Mark as direct enrollment
            series_enrollment_id=None,
            auto_enrolled=False,
            streak_count=0,
            longest_streak=0,
            status=UserPlanStatus.NOT_STARTED,
            started_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc), 
            is_completed=False,
        )
        save_plan_progress(db=db, plan_progress=new_progress)
    

def unenroll_user_from_plan(token: str, plan_id: UUID) -> None:

    current_user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        delete_user_plan_progress(db=db, user_id=current_user.id, plan_id=plan_id)


def get_user_plan_progress(token: str, plan_id: UUID) -> UserPlanProgressResponse:
    """Get user's progress for a specific plan"""
    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        # Get user's progress record from database
        progress_record = get_plan_progress_by_user_id_and_plan_id(
            db=db, user_id=current_user.id, plan_id=plan_id
        )
        
        if not progress_record:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error="NOT_FOUND",
                    message="User not enrolled in this plan"
                ).model_dump()
            )
        
        # Get plan details from database
        plan = get_plan_by_id(db=db, plan_id=plan_id)
        
        if not plan:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(
                    error="NOT_FOUND",
                    message=ErrorConstants.PLAN_NOT_FOUND
                ).model_dump()
            )
        
        plan_image = safe_get_image_url(
            plan.image_url, resource_id=plan.id, resource_type="plan"
        )

        from pecha_api.plans.videos.plan_video_repository import get_plan_videos_by_plan_id
        from pecha_api.plans.public.plan_response_models import PlanVideoSummaryDTO

        plan_videos = get_plan_videos_by_plan_id(db=db, plan_id=plan_id)
        
        # Build plan details dict
        plan_details = {
            "id": str(plan.id),
            "title": plan.title,
            "description": plan.description,
            "language": plan.language.value if plan.language else None,
            "difficulty_level": plan.difficulty_level.value if plan.difficulty_level else None,
            "image": plan_image.model_dump() if plan_image else None,
            "tags": [t.model_dump() for t in tags_to_summary_dtos(plan.tag_list)],
            "videos": [
                PlanVideoSummaryDTO(
                    id=video.id,
                    url=video.url,
                    video_id=video.video_id,
                    title=video.title,
                    display_order=video.display_order,
                ).model_dump()
                for video in plan_videos
            ],
        }
        
        return UserPlanProgressResponse(
            id=progress_record.id,
            user_id=progress_record.user_id,
            plan_id=progress_record.plan_id,
            plan=plan_details,
            started_at=progress_record.started_at,
            streak_count=progress_record.streak_count or 0,
            longest_streak=progress_record.longest_streak or 0,
            status=progress_record.status.value if hasattr(progress_record.status, 'value') else str(progress_record.status),
            is_completed=progress_record.is_completed or False,
            completed_at=progress_record.completed_at,
            created_at=progress_record.created_at
        )

def complete_sub_task_service(token: str, id: UUID) -> None:

    current_user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        existing_sub_task = get_sub_task_by_subtask_id(db=db, id=id)
        if not existing_sub_task:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(error=BAD_REQUEST, message=SUB_TASK_NOT_FOUND).model_dump()
            )

        existing_completion = get_user_sub_task_by_user_id_and_sub_task_id(
            db=db, user_id=current_user.id, sub_task_id=id
        )
        if existing_completion:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=ResponseError(error=BAD_REQUEST, message=ALREADY_COMPLETED_SUB_TASK).model_dump()
            )
        
        task = get_task_by_id(db=db, task_id=existing_sub_task.task_id)
        new_sub_task_completion = UserSubTaskCompletion(
            user_id=current_user.id,
            sub_task_id=existing_sub_task.id,
        )
        save_user_sub_task_completions(db=db, user_sub_task_completions=new_sub_task_completion)
        is_all_subtasks_completed = _check_all_subtasks_completed(user_id=current_user.id, task_id=existing_sub_task.task_id)
        if is_all_subtasks_completed:
            new_task_completion = UserTaskCompletion(
                user_id=current_user.id,
                task_id=existing_sub_task.task_id
            )   
            save_user_task_completion(db=db, user_task_completion=new_task_completion)
        check_day_completion(db=db, user_id=current_user.id, day_id=task.plan_item_id)


def _check_all_subtasks_completed(user_id: UUID, task_id: UUID) -> bool:
    with SessionLocal() as db:
        sub_tasks = get_sub_tasks_by_task_id(db=db, task_id=task_id)
        sub_task_ids = [sub_task.id for sub_task in sub_tasks]
        uncompleted_sub_task_ids = get_uncompleted_user_sub_task_ids(db=db, user_id=user_id, sub_task_ids=sub_task_ids)
        return len(uncompleted_sub_task_ids) == 0

def complete_task_service(token: str, task_id: UUID) -> None:

    current_user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        task = get_task_by_id(db=db, task_id=task_id)
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ResponseError(error=BAD_REQUEST, message=TASK_NOT_FOUND).model_dump())

        complete_all_subtasks_completions(db=db, user_id=current_user.id, task_id=task.id)
        new_task_completion = UserTaskCompletion(
            user_id=current_user.id,
            task_id=task.id
        )
        save_user_task_completion(db=db, user_task_completion=new_task_completion)
        check_day_completion(db=db, user_id=current_user.id, day_id=task.plan_item_id)


def complete_all_subtasks_completions(db:SessionLocal(), user_id: UUID, task_id: UUID) -> None:

    sub_tasks = get_sub_tasks_by_task_id(db=db, task_id=task_id)
    sub_tasks_ids = [sub_task.id for sub_task in sub_tasks]
    uncompleted_sub_task_ids = get_uncompleted_user_sub_task_ids(db=db, user_id=user_id, sub_task_ids=sub_tasks_ids)
    new_subtask_to_create = [UserSubTaskCompletion(user_id=user_id, sub_task_id=sub_task_id) for sub_task_id in uncompleted_sub_task_ids]
    save_user_sub_task_completions_bulk(db=db, user_sub_task_completions=new_subtask_to_create)

def check_day_completion(db:SessionLocal(), user_id: UUID, day_id: UUID) -> None:
    tasks = get_tasks_by_plan_item_id(db=db, plan_item_id=day_id)
    task_ids = [task.id for task in tasks]
    uncompleted_task_ids = get_uncompleted_user_task_ids(db=db, user_id=user_id, task_ids=task_ids)
    
    if len(uncompleted_task_ids) == 0:
        save_user_day_completion(db=db, user_day_completion=UserDayCompletion(user_id=user_id, day_id=day_id))
        schedule_invalidate_user_stats_cache(user_id=user_id)

        sibling_day_ids = sync_series_day_completion(db=db, user_id=user_id, completed_day_id=day_id)

        check_plan_completion(db, user_id, day_id)
        for sibling_day_id in sibling_day_ids:
            check_plan_completion(db, user_id, sibling_day_id)
    else:
        return


def check_plan_completion(db: SessionLocal, user_id: UUID, day_id: UUID) -> None:
    """Check if plan is completed after a day completion and trigger series progression if needed"""
    from pecha_api.plans.items.plan_items_repository import get_plan_item_by_id
    
    # Get the plan ID from the day
    day_item = get_plan_item_by_id(db, day_id)
    if not day_item:
        return
    
    plan_id = day_item.plan_id
    
    # Get all days in the plan
    days = get_days_by_plan_id(db, plan_id)
    day_ids = [day.id for day in days]
    
    # Check if all days are completed
    completed_day_ids = get_completed_day_ids_by_user_id_and_day_ids(db, user_id, day_ids)
    
    if len(completed_day_ids) == len(day_ids):  # All days completed
        # Mark plan as completed and trigger series progression
        handle_plan_completion_and_series_progression(db, user_id, plan_id)

def delete_task_service(token: str, task_id: UUID) -> None:
    current_user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        task = get_task_by_id(db=db, task_id=task_id)
        if not task:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ResponseError(error=BAD_REQUEST, message=TASK_NOT_FOUND).model_dump())

        delete_user_task_completion(db=db, user_id=current_user.id, task_id=task.id)

        delete_user_day_completion(db=db, user_id=current_user.id, day_id=task.plan_item_id)
        schedule_invalidate_user_stats_cache(user_id=current_user.id)

        sub_tasks = get_sub_tasks_by_task_id(db=db, task_id=task.id)
        sub_tasks_ids = [sub_task.id for sub_task in sub_tasks]
        delete_user_subtask_completion(db=db, user_id=current_user.id, sub_task_ids=sub_tasks_ids)


async def get_user_plan_days_completion_status_service(token: str, plan_id: UUID) ->  UserPlanDayCompletionStatusResponse:
    current_user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        plan = get_plan_by_id(db=db, plan_id=plan_id)
        if not plan:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=PLAN_NOT_FOUND)
        
        days = get_days_by_plan_id(db=db, plan_id=plan_id)
        day_ids = [day.id for day in days]
        completed_day_ids = get_completed_day_ids_by_user_id_and_day_ids(
            db=db, 
            user_id=current_user.id, 
            day_ids=day_ids
        )
        
        days_completion_status: List[UserPlanDayCompletionStatus] = [
            UserPlanDayCompletionStatus(
                day_number=day.day_number,
                is_completed=(day.id in completed_day_ids)
            )
            for day in days
        ]
        
        return UserPlanDayCompletionStatusResponse(
            days=days_completion_status,
            start_date=plan.start_date
        )
    
async def get_user_plan_day_details_service(token: str, plan_id: UUID, day_number: int) -> UserPlanDayDetailsResponse:
    current_user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        plan_item = get_plan_day_with_tasks_and_subtasks(db=db, plan_id=plan_id, day_number=day_number)
        plan = get_plan_by_id(db=db, plan_id=plan_id)
        plan_language = getattr(plan, "language", None)
        completed_task_ids = []
        completed_subtask_ids = set()
        task_ids = [task.id for task in plan_item.tasks]
        if task_ids:
            user_task_completions = get_user_task_completions_by_user_id_and_task_ids(db=db, user_id=current_user.id, task_ids=task_ids)
            completed_task_ids = [completion.task_id for completion in user_task_completions]

        sub_task_ids = [sub_task.id for task in plan_item.tasks for sub_task in task.sub_tasks]
        if sub_task_ids:
            user_subtask_completions = get_user_subtask_completions_by_user_id_and_sub_task_ids(db=db, user_id=current_user.id, sub_task_ids=sub_task_ids)
            completed_subtask_ids = {completion.sub_task_id for completion in user_subtask_completions}

        from pecha_api.plans.audio.dto_helpers import (
            build_plan_day_audio_fields,
            build_plan_day_shareable_image_fields,
        )

        audio_url, audio_duration_ms, _, _ = build_plan_day_audio_fields(plan_item)
        thumbnail_url, _, shareable_image_url, _ = build_plan_day_shareable_image_fields(
            getattr(plan_item, "shareable_images", None)
        )
        from pecha_api.plans.public.plan_response_models import DayVideoSummaryDTO
        tasks_sub_tasks = await asyncio.gather(
            *[
                _get_user_sub_tasks_dto_bulk(
                    sub_tasks=task.sub_tasks,
                    completed_subtask_ids=completed_subtask_ids,
                    language=plan_language,
                )
                for task in plan_item.tasks
            ]
        )
        user_day_details = UserPlanDayDetailsResponse(
            id=plan_item.id,
            day_number=plan_item.day_number,
            is_completed=is_day_completed(db=db, user_id=current_user.id, day_id=plan_item.id),
            audio_url=audio_url,
            audio_duration_ms=audio_duration_ms,
            thumbnail_url=thumbnail_url,
            shareable_image_url=shareable_image_url,
            tasks=[
                UserTaskDTO(
                    id=task.id,
                    title=task.title,
                    estimated_time=task.estimated_time,
                    display_order=task.display_order,
                    is_completed=(task.id in completed_task_ids),
                    sub_tasks=sub_tasks_dto
                ) for task, sub_tasks_dto in zip(plan_item.tasks, tasks_sub_tasks)
            ],
            videos=[
                DayVideoSummaryDTO(
                    id=video.id,
                    url=video.url,
                    video_id=video.video_id,
                    title=video.title,
                    display_order=video.display_order,
                )
                for video in sorted(plan_item.videos, key=lambda v: v.display_order)
            ],
        )
        return user_day_details

def is_day_completed(db: SessionLocal(), user_id: UUID, day_id: UUID) -> bool:
    user_day_completion = get_user_day_completion_by_user_id_and_day_id(db=db, user_id=user_id, day_id=day_id)
    return user_day_completion is not None

async def _get_user_sub_tasks_dto_bulk(sub_tasks: List[PlanSubTask], completed_subtask_ids: Set[UUID], language=None) -> List[UserSubTaskDTO]:
    from pecha_api.plans.audio.dto_helpers import build_subtask_timestamp_fields

    from pecha_api.plans.shared.subtask_reference_resolver import resolve_subtask_references

    resolved_contents = await resolve_subtasks_content(sub_tasks)
    resolved_references = resolve_subtask_references(subtasks=sub_tasks, language=language)

    result = []
    for sub_task, resolved_content, reference in zip(sub_tasks, resolved_contents, resolved_references):
        start_ms, end_ms = build_subtask_timestamp_fields(sub_task)
        audio_url = (
            _get_presigned_url(content=sub_task.audio_url)
            if sub_task.audio_url else None
        )
        result.append(
            UserSubTaskDTO(
                id=sub_task.id,
                content_type=sub_task.content_type,
                content=_get_presigned_url(content=sub_task.content) if sub_task.content_type == ContentType.IMAGE else resolved_content,
                duration=sub_task.duration,
                display_order=sub_task.display_order,
                is_completed=(sub_task.id in completed_subtask_ids),
                audio_url=audio_url,
                source_text_id=sub_task.source_text_id,
                pecha_segment_id=sub_task.pecha_segment_id,
                segment_ids=sub_task.segment_ids,
                segment_numbers=sub_task.segment_numbers,
                reference_id=sub_task.reference_id,
                reference=reference,
                start_ms=start_ms,
                end_ms=end_ms,
            )
        )
    return result

def _get_presigned_url(content: str) -> str:
    return generate_presigned_access_url(
        bucket_name=get("AWS_BUCKET_NAME"),
        s3_key=content
    )


# Series Enrollment Service Functions

def _compute_series_plan_progress(all_plans: list, progress_by_plan_id: dict) -> tuple[int, int, float]:
    total_plans = len(all_plans)
    if total_plans == 0:
        return 0, 0, 0.0
    completed_plans = sum(
        1
        for plan in all_plans
        if (progress := progress_by_plan_id.get(plan.id)) and progress.is_completed
    )
    return total_plans, completed_plans, completed_plans / total_plans * 100


def _series_metadata_language(metadata) -> str:
    language = metadata.language
    return language.value if hasattr(language, "value") else str(language)


def _select_series_metadata(metadata_entries, language: Optional[str]):
    """Pick a series metadata entry for ``language``, falling back to 'en', then first."""
    if not metadata_entries:
        return None
    matched = filter_by_language_with_fallback(
        entries=list(metadata_entries),
        language=language,
        language_of=_series_metadata_language,
    )
    return matched[0] if matched else metadata_entries[0]


def _build_user_series_enrollment_dto(
    enrollment: UserSeriesEnrollment,
    series: Series,
    current_plan_title_by_id: dict,
    plans_by_series_id: dict,
    progress_by_plan_id: dict,
    group: Optional[AuthorGroupSummaryDTO] = None,
    language: Optional[str] = None,
    partner_group_id: Optional[UUID] = None,
    enrolled_count: int = 0,
    completed_day_count: int = 0,
) -> UserSeriesEnrollmentDTO:
    series_metadata = _select_series_metadata(series.metadata_entries, language)
    series_image = safe_get_image_url(
        series.image, resource_id=series.id, resource_type="series"
    )
    current_plan_title = (
        current_plan_title_by_id.get(enrollment.current_plan_id)
        if enrollment.current_plan_id
        else None
    )
    all_plans = plans_by_series_id.get(enrollment.series_id, [])
    total_plans, completed_plans, progress_percentage = _compute_series_plan_progress(
        all_plans, progress_by_plan_id
    )
    series_progress = _series_progress_from_plans(
        all_plans,
        language=language,
        completed_day_count=completed_day_count,
    )
    partner = (
        build_series_partner_dto(group, language=language)
        if partner_group_id
        else None
    )
    return UserSeriesEnrollmentDTO(
        id=enrollment.id,
        user_id=enrollment.user_id,
        series_id=enrollment.series_id,
        series_title=series_metadata.title if series_metadata else "Untitled Series",
        series_description=series_metadata.description if series_metadata else None,
        image=series_image,
        enrolled_at=enrollment.enrolled_at,
        status=enrollment.status.value if hasattr(enrollment.status, 'value') else str(enrollment.status),
        auto_enroll_next=enrollment.auto_enroll_next,
        current_plan_id=enrollment.current_plan_id,
        current_plan_title=current_plan_title,
        is_completed=enrollment.is_completed,
        completed_at=enrollment.completed_at,
        total_plans=total_plans,
        completed_plans=completed_plans,
        progress_percentage=progress_percentage,
        enrolled_count=enrolled_count,
        group=group,
        series_partner_id=partner_group_id,
        progress=series_progress,
        partner=partner,
    )


def _build_series_plan_dto_for_progress(
    db,
    plan,
    user_id: UUID,
    group: Optional[AuthorGroupSummaryDTO] = None,
) -> UserPlanDTO:
    total_days = len(get_days_by_plan_id(db, plan.id))
    progress = get_plan_progress_by_user_id_and_plan_id(db, user_id, plan.id)
    started_at = progress.started_at if progress else None
    return UserPlanDTO(
        id=plan.id,
        title=plan.title,
        description=plan.description or "",
        language=plan.language.value if hasattr(plan.language, 'value') else str(plan.language),
        difficulty_level=plan.difficulty_level.value if hasattr(plan.difficulty_level, 'value') else str(plan.difficulty_level),
        image=safe_get_image_url(plan.image_url, resource_id=plan.id, resource_type="plan"),
        started_at=started_at,
        total_days=total_days,
        tags=tags_to_summary_dtos(plan.tag_list),
        start_date=plan.start_date,
        display_order=plan.display_order,
        group=group,
    )


def _resolve_series_partner_id(
    db,
    series_id: UUID,
    group_id: Optional[UUID],
) -> Optional[UUID]:
    if group_id is None:
        return None
    series_partner = get_series_partner(db, series_id, group_id)
    if series_partner is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ResponseError(
                error=BAD_REQUEST,
                message="Group is not a partner of this series",
            ).model_dump(),
        )
    return series_partner.id


def enroll_user_in_series(token: str, enroll_request: UserSeriesEnrollRequest) -> None:
    """Enroll user in a series, or update partner group when already enrolled."""
    current_user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        series = db.query(Series).filter(Series.id == enroll_request.series_id).first()
        if not series:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(error=BAD_REQUEST, message="Series not found").model_dump()
            )

        existing_enrollment = get_user_series_enrollment_by_user_and_series(
            db, current_user.id, enroll_request.series_id
        )
        if existing_enrollment:
            if "group_id" not in enroll_request.model_fields_set:
                return

            new_partner_id = _resolve_series_partner_id(
                db, enroll_request.series_id, enroll_request.group_id
            )
            if existing_enrollment.series_partner_id != new_partner_id:
                existing_enrollment.series_partner_id = new_partner_id
                update_user_series_enrollment(db, existing_enrollment)

            if enroll_request.group_id is not None:
                upsert_group_join(db, enroll_request.group_id, current_user.id)
            return

        new_partner_id = _resolve_series_partner_id(
            db, enroll_request.series_id, enroll_request.group_id
        )

        first_plan = None
        if enroll_request.start_immediately:
            first_plan = get_first_plan_in_series(db, enroll_request.series_id)

        new_enrollment = UserSeriesEnrollment(
            user_id=current_user.id,
            series_id=enroll_request.series_id,
            status=SeriesStatus.ACTIVE,
            auto_enroll_next=enroll_request.auto_enroll_next,
            current_plan_id=first_plan.id if first_plan else None,
            series_partner_id=new_partner_id,
            enrolled_at=datetime.now(timezone.utc),
            created_at=datetime.now(timezone.utc),
            is_completed=False,
        )
        save_user_series_enrollment(db, new_enrollment)

        if enroll_request.group_id is not None:
            upsert_group_join(db, enroll_request.group_id, current_user.id)

        if enroll_request.start_immediately and first_plan:
            auto_enroll_in_next_plan(db, current_user.id, first_plan.id, new_enrollment.id)


def get_user_series_enrollments(
    token: str, 
    status_filter: Optional[str] = None,
    language: Optional[str] = None,
    skip: int = 0, 
    limit: int = 20
) -> UserSeriesEnrollmentsResponse:
    """Get user's series enrollments"""
    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        enrollments, total = get_user_series_enrollments_by_user_id(
            db, current_user.id, status_filter, skip, limit
        )

        if not enrollments:
            return UserSeriesEnrollmentsResponse(
                enrollments=[],
                skip=skip,
                limit=limit,
                total=total,
            )

        series_ids = [enrollment.series_id for enrollment in enrollments]
        current_plan_ids = [
            enrollment.current_plan_id
            for enrollment in enrollments
            if enrollment.current_plan_id
        ]

        series_by_id = {series.id: series for series in get_series_by_ids(db, series_ids)}
        plans_by_series_id = get_plans_by_series_ids(db, series_ids)

        all_plan_ids = [
            plan.id
            for plans in plans_by_series_id.values()
            for plan in plans
        ]
        progress_by_plan_id = get_plan_progress_by_user_id_and_plan_ids(
            db, current_user.id, all_plan_ids
        )
        current_plan_title_by_id = {
            plan.id: plan.title
            for plan in get_plans_by_ids(db, current_plan_ids)
        }
        series_group_ids = get_group_ids_by_series_ids(db=db, series_ids=series_ids)
        series_partner_ids = [
            enrollment.series_partner_id
            for enrollment in enrollments
            if getattr(enrollment, "series_partner_id", None)
        ]
        partner_group_id_by_series_partner_id = get_group_ids_by_series_partner_ids(
            db=db, series_partner_ids=series_partner_ids
        )
        group_ids_for_summaries = set(series_group_ids.values())
        group_ids_for_summaries.update(partner_group_id_by_series_partner_id.values())
        group_summaries = get_group_summaries_by_ids(
            db=db, group_ids=list(group_ids_for_summaries), language=language
        )
        enrolled_count_map = get_enrolled_count_map_by_series_ids(
            db=db, series_ids=series_ids
        )
        plan_ids_by_series = {
            series_id: get_language_filtered_series_plan_ids(plans, language=language)
            for series_id, plans in plans_by_series_id.items()
        }
        completed_days_by_series = get_user_completed_days_count_by_series_ids(
            db=db,
            user_id=current_user.id,
            series_ids=series_ids,
            plan_ids_by_series=plan_ids_by_series,
        )

        enrollment_dtos = [
            _build_user_series_enrollment_dto(
                enrollment,
                series,
                current_plan_title_by_id,
                plans_by_series_id,
                progress_by_plan_id,
                group=_group_summary_for_id(
                    partner_group_id_by_series_partner_id.get(enrollment.series_partner_id)
                    if getattr(enrollment, "series_partner_id", None)
                    else series_group_ids.get(enrollment.series_id),
                    group_summaries,
                ),
                language=language,
                partner_group_id=(
                    partner_group_id_by_series_partner_id.get(enrollment.series_partner_id)
                    if getattr(enrollment, "series_partner_id", None)
                    else None
                ),
                enrolled_count=enrolled_count_map.get(enrollment.series_id, 0),
                completed_day_count=completed_days_by_series.get(enrollment.series_id, 0),
            )
            for enrollment in enrollments
            if (series := series_by_id.get(enrollment.series_id))
        ]
        
        return UserSeriesEnrollmentsResponse(
            enrollments=enrollment_dtos,
            skip=skip,
            limit=limit,
            total=total
        )


def get_user_series_days_completed(
    token: str,
    language: Optional[str] = None,
    skip: int = 0,
    limit: int = 20,
) -> UserSeriesDaysCompletedResponse:
    """Get paginated list of series with completed day counts for the current user."""
    current_user = validate_and_extract_user_details(token=token)

    with SessionLocal() as db:
        rows, total = get_user_series_days_completed_paginated(
            db=db,
            user_id=current_user.id,
            skip=skip,
            limit=limit,
        )

        if not rows:
            return UserSeriesDaysCompletedResponse(
                series=[],
                skip=skip,
                limit=limit,
                total=total,
            )

        series_ids = [series_id for series_id, _ in rows]
        series_by_id = {series.id: series for series in get_series_by_ids(db, series_ids)}
        plans_by_series_id = get_plans_by_series_ids(db, series_ids)
        series_group_ids = get_group_ids_by_series_ids(db=db, series_ids=series_ids)
        group_summaries = get_group_summaries_by_ids(
            db=db, group_ids=list(series_group_ids.values()), language=language
        )
        enrolled_count_map = get_enrolled_count_map_by_series_ids(
            db=db, series_ids=series_ids
        )
        enrollment_partner_map = get_user_series_enrollment_partner_map(
            db=db,
            user_id=current_user.id,
            series_ids=series_ids,
        )
        partner_group_by_series, partner_dto_by_series = _load_series_partner_context(
            db=db,
            user_id=current_user.id,
            series_ids=series_ids,
            language=language,
        )

        series_dtos = []
        for series_id, _days_completed in rows:
            series = series_by_id.get(series_id)
            if not series:
                continue
            series_metadata = _select_series_metadata(series.metadata_entries, language)
            series_plans = plans_by_series_id.get(series_id, [])
            language_plan_ids = get_language_filtered_series_plan_ids(
                series_plans,
                language=language,
            )
            completed_day_count = count_user_completed_days_for_plan_ids(
                db=db,
                user_id=current_user.id,
                plan_ids=language_plan_ids,
            )
            series_progress = _series_progress_from_plans(
                series_plans,
                language=language,
                completed_day_count=completed_day_count,
            )
            series_dtos.append(
                UserSeriesDaysCompletedDTO(
                    series_id=series_id,
                    series_title=series_metadata.title if series_metadata else "Untitled Series",
                    series_description=series_metadata.description if series_metadata else None,
                    image=safe_get_image_url(
                        series.image, resource_id=series.id, resource_type="series"
                    ),
                    days_completed=completed_day_count,
                    enrolled_count=enrolled_count_map.get(series_id, 0),
                    group=_resolve_series_group_for_user(
                        series_id,
                        series_group_ids=series_group_ids,
                        group_summaries=group_summaries,
                        partner_group_by_series=partner_group_by_series,
                        enrollment_partner_map=enrollment_partner_map,
                    ),
                    progress=series_progress,
                    partner=partner_dto_by_series.get(series_id),
                )
            )

        return UserSeriesDaysCompletedResponse(
            series=series_dtos,
            skip=skip,
            limit=limit,
            total=total,
        )


def get_user_series_progress(
    token: str,
    series_id: UUID,
    language: Optional[str] = None,
) -> UserSeriesProgressResponse:
    """Get detailed progress for a specific series"""
    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        # Get enrollment
        enrollment = get_user_series_enrollment_by_user_and_series(db, current_user.id, series_id)
        if not enrollment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(error="NOT_FOUND", message="Not enrolled in this series").model_dump()
            )
        
        # Get series details
        series = db.query(Series).filter(Series.id == series_id).first()
        if not series:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(error="NOT_FOUND", message="Series not found").model_dump()
            )
        
        series_metadata = _select_series_metadata(series.metadata_entries, language)
        all_plans = get_plans_by_series_id(db, series_id)
        group_summaries, plan_group_ids, series_group_ids = _load_group_summaries_for_plans(
            db, all_plans, extra_series_ids=[series_id], language=language
        )
        series_group_id = series_group_ids.get(series_id)
        series_group = _group_summary_for_id(series_group_id, group_summaries)
        plan_dtos = [
            _build_series_plan_dto_for_progress(
                db,
                plan,
                current_user.id,
                group=_group_summary_for_id(
                    _resolve_plan_group_id(plan, plan_group_ids, series_group_ids),
                    group_summaries,
                ),
            )
            for plan in all_plans
        ]
        enrolled_count = get_enrolled_count_map_by_series_ids(
            db=db, series_ids=[series_id]
        ).get(series_id, 0)
        language_plan_ids = get_language_filtered_series_plan_ids(
            all_plans,
            language=language,
        )
        completed_day_count = count_user_completed_days_for_plan_ids(
            db=db,
            user_id=current_user.id,
            plan_ids=language_plan_ids,
        )
        series_progress = _series_progress_from_plans(
            all_plans,
            language=language,
            completed_day_count=completed_day_count,
        )
        partner_group = None
        if getattr(enrollment, "series_partner_id", None):
            partner_group_id = get_group_ids_by_series_partner_ids(
                db=db, series_partner_ids=[enrollment.series_partner_id]
            ).get(enrollment.series_partner_id)
            if partner_group_id:
                partner_summaries = get_group_summaries_by_ids(
                    db=db, group_ids=[partner_group_id], language=language
                )
                partner_group = partner_summaries.get(partner_group_id)

        return UserSeriesProgressResponse(
            id=enrollment.id,
            series_id=series_id,
            series_title=series_metadata.title if series_metadata else "Untitled Series",
            series_description=series_metadata.description if series_metadata else None,
            enrolled_at=enrollment.enrolled_at,
            status=enrollment.status.value if hasattr(enrollment.status, 'value') else str(enrollment.status),
            auto_enroll_next=enrollment.auto_enroll_next,
            current_plan_id=enrollment.current_plan_id,
            is_completed=enrollment.is_completed,
            completed_at=enrollment.completed_at,
            plans=plan_dtos,
            enrolled_count=enrolled_count,
            group=series_group,
            progress=series_progress,
            partner=build_series_partner_dto(partner_group, language=language),
        )


def update_user_series_enrollment_service(
    token: str, 
    series_id: UUID, 
    update_request: UpdateSeriesEnrollmentRequest
) -> None:
    """Update series enrollment settings"""
    current_user = validate_and_extract_user_details(token=token)
    
    with SessionLocal() as db:
        enrollment = get_user_series_enrollment_by_user_and_series(db, current_user.id, series_id)
        if not enrollment:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(error="NOT_FOUND", message="Not enrolled in this series").model_dump()
            )
        
        # Update fields
        if update_request.auto_enroll_next is not None:
            enrollment.auto_enroll_next = update_request.auto_enroll_next
        
        if update_request.status is not None:
            enrollment.status = update_request.status
        
        update_user_series_enrollment(db, enrollment)


def unenroll_user_from_series(token: str, series_id: UUID) -> None:
    """Unenroll user from series"""
    current_user = validate_and_extract_user_details(token=token)
    with SessionLocal() as db:
        delete_user_series_enrollment(db, current_user.id, series_id)
