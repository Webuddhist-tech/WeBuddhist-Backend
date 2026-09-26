from fastapi import APIRouter, Query, Depends
from typing import Optional
from uuid import UUID
from starlette import status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated

from pecha_api.plans.language_constants import language_query_description
from pecha_api.plans.plans_response_models import PlansResponse
from pecha_api.plans.users.plan_users_response_models import (
    UserPlanEnrollRequest, 
    UserPlanProgressResponse, 
    UserPlanDayDetailsResponse,
    UserPlansResponse,
    UserPlanDayCompletionStatusResponse,
    UserSeriesEnrollRequest,
    UserSeriesEnrollmentsResponse,
    UserSeriesProgressResponse,
    UpdateSeriesEnrollmentRequest,
    UserSeriesDaysCompletedResponse,
)

from pecha_api.plans.users.plan_users_service import (
    get_user_enrolled_plans,
    enroll_user_in_plan,
    get_user_plan_days_completion_status_service,
    unenroll_user_from_plan,
    get_user_plan_progress,
    complete_task_service,
    complete_sub_task_service,
    delete_task_service,
    get_user_plan_day_details_service,
    enroll_user_in_series,
    get_user_series_enrollments,
    get_user_series_progress,
    get_user_series_days_completed,
    update_user_series_enrollment_service,
    unenroll_user_from_series
)


oauth2_scheme = HTTPBearer()

from pecha_api.cache.cache_invalidation_deps import invalidate_caller_on_write
from pecha_api.plans.users.user_plans_cache_service import (
    USER_PLAN_CACHE_TYPES,
    get_user_plan_days_completion_status_cached,
    get_user_plan_progress_cached,
    get_user_plans_cached,
    get_user_series_days_completed_cached,
    get_user_series_enrollments_cached,
    get_user_series_progress_cached,
)

user_progress_router = APIRouter(
    prefix="/users/me",
    tags=["User Progress"],
    # Completing a subtask or enrolling changes only this caller's progress.
    dependencies=[Depends(invalidate_caller_on_write(*USER_PLAN_CACHE_TYPES))],
)


@user_progress_router.get("/plans", status_code=status.HTTP_200_OK, response_model=UserPlansResponse)
async def get_user_plans(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    status_filter: Optional[str] = Query(None, description="Filter by series enrollment status (ACTIVE, PAUSED, COMPLETED, CANCELLED)"),
    series_id: Optional[UUID] = Query(None, description="Filter by series ID to only get plans from that series"),
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Filter group metadata by language", lowercase_example=True)),
    ] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50)
):

    return await get_user_plans_cached(
        token=authentication_credential.credentials,
        status_filter=status_filter,
        series_id=series_id,
        language=language,
        skip=skip,
        limit=limit,
    )


@user_progress_router.post("/plans", status_code=status.HTTP_204_NO_CONTENT)
def enroll_in_plan(
    enroll_request: UserPlanEnrollRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    enroll_user_in_plan(
        token=authentication_credential.credentials,
        enroll_request=enroll_request
    )

@user_progress_router.delete("/plans/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def unenroll_from_plan(
    plan_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    unenroll_user_from_plan(
        token=authentication_credential.credentials,
        plan_id=plan_id
    )

@user_progress_router.get("/plans/{plan_id}", status_code=status.HTTP_200_OK, response_model=UserPlanProgressResponse)
async def get_user_plan_progress_details(
    plan_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    """Get user's progress for specific plan"""
    return await get_user_plan_progress_cached(
        token=authentication_credential.credentials,
        plan_id=plan_id
    )

@user_progress_router.get("/plans/{plan_id}/days/completion_status", status_code=status.HTTP_200_OK, response_model=UserPlanDayCompletionStatusResponse)
async def get_user_plan_days_completion_status(
    plan_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return await get_user_plan_days_completion_status_cached(
        token=authentication_credential.credentials, plan_id=plan_id
    )

@user_progress_router.post("/sub-tasks/{sub_task_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
def complete_sub_task(
    sub_task_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    complete_sub_task_service(
        token=authentication_credential.credentials,
        id=sub_task_id
    )

@user_progress_router.post("/tasks/{task_id}/complete", status_code=status.HTTP_204_NO_CONTENT)
def complete_task(
    task_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return complete_task_service(
        token=authentication_credential.credentials,
        task_id=task_id
    )


@user_progress_router.delete("/task/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(
    task_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    return delete_task_service(
        token=authentication_credential.credentials,
        task_id=task_id
    )


@user_progress_router.get("/plan/{plan_id}/days/{day_number}", status_code=status.HTTP_200_OK, response_model=UserPlanDayDetailsResponse)
async def get_user_plan_day_details(
    plan_id: UUID,
    day_number: int,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    # Deliberately uncached. Everything here is the caller's own progress, and
    # a day reopened right after finishing a subtask has to show that subtask
    # finished - not a copy of the response taken before it was. What made this
    # endpoint slow was never the read of that progress, it was re-resolving
    # every openpecha segment on the day; those are cached by segment id in
    # `plans/shared/segment_cache.py`, where the entry is shared by every
    # reader instead of being rebuilt per user.
    return await get_user_plan_day_details_service(
        token=authentication_credential.credentials,
        plan_id=plan_id,
        day_number=day_number
    )


# Series Enrollment Endpoints

@user_progress_router.post("/series", status_code=status.HTTP_204_NO_CONTENT)
def enroll_in_series(
    enroll_request: UserSeriesEnrollRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    """Enroll user in a series"""
    enroll_user_in_series(
        token=authentication_credential.credentials,
        enroll_request=enroll_request
    )


@user_progress_router.get("/series", status_code=status.HTTP_200_OK, response_model=UserSeriesEnrollmentsResponse)
async def get_user_series_enrollments_endpoint(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    status_filter: Annotated[Optional[str], Query(description="Filter by series enrollment status")] = None,
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Filter group metadata by language", lowercase_example=True)),
    ] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    """Get user's series enrollments"""
    return await get_user_series_enrollments_cached(
        token=authentication_credential.credentials,
        status_filter=status_filter,
        language=language,
        skip=skip,
        limit=limit
    )


@user_progress_router.get(
    "/series/day-completed",
    status_code=status.HTTP_200_OK,
    response_model=UserSeriesDaysCompletedResponse,
)
async def get_user_series_days_completed_endpoint(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Filter group metadata by language", lowercase_example=True)),
    ] = None,
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
):
    """Get paginated list of series with completed day counts for the current user."""
    return await get_user_series_days_completed_cached(
        token=authentication_credential.credentials,
        language=language,
        skip=skip,
        limit=limit,
    )


@user_progress_router.get("/series/{series_id}", status_code=status.HTTP_200_OK, response_model=UserSeriesProgressResponse)
async def get_user_series_progress_endpoint(
    series_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Filter group metadata by language", lowercase_example=True)),
    ] = None,
):
    """Get detailed progress for a specific series"""
    return await get_user_series_progress_cached(
        token=authentication_credential.credentials,
        series_id=series_id,
        language=language,
    )


@user_progress_router.patch("/series/{series_id}", status_code=status.HTTP_204_NO_CONTENT)
def update_series_enrollment(
    series_id: UUID,
    update_request: UpdateSeriesEnrollmentRequest,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    """Update series enrollment settings"""
    update_user_series_enrollment_service(
        token=authentication_credential.credentials,
        series_id=series_id,
        update_request=update_request
    )


@user_progress_router.delete("/series/{series_id}", status_code=status.HTTP_204_NO_CONTENT)
def unenroll_from_series(
    series_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)]
):
    """Unenroll user from series"""
    unenroll_user_from_series(
        token=authentication_credential.credentials,
        series_id=series_id
    )