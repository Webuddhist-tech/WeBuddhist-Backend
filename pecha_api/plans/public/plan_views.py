from fastapi import APIRouter, HTTPException, Query, Depends, Request, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated, Optional
from uuid import UUID
from datetime import date as DateType
from starlette import status
from starlette.concurrency import run_in_threadpool

from pecha_api import config
from pecha_api.db.database import SessionLocal
from pecha_api.plans.language_constants import language_query_description
from pecha_api.plans.public.plan_response_models import (
    PublicPlansResponse,
    PublicPlanDTO,
    PlanDaysResponse,
    PlanDayDTO,
    PlanDayCacheCleanupResponse,
    TagsResponse,
    DailyPlanResponse,
)
from pecha_api.plans.public.plans_cache_service import (
    invalidate_all_plan_day_detail_caches_for_plan,
    invalidate_plan_day_detail_cache,
)
from pecha_api.plans.public.plan_service import (
    get_published_plans, 
    get_published_plan, 
    get_plan_days,
    get_plan_day_details,
    get_plan_daily_content,
    get_tags,
    auto_enroll_plan
)
from pecha_api.users.users_service import validate_and_extract_user_details

optional_oauth2_scheme = HTTPBearer(auto_error=False)


def _require_debug_deployment_mode() -> None:
    if config.get("DEPLOYMENT_MODE").upper() != "DEBUG":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cache cleanup is only available when DEPLOYMENT_MODE is DEBUG.",
        )


# Create router for public plan endpoints
public_plans_router = APIRouter(
    prefix="/plans",
    tags=["Public Plans"]
)


@public_plans_router.get("", status_code=status.HTTP_200_OK, response_model=PublicPlansResponse)
async def get_plans(
    tag: Annotated[Optional[str], Query(description="Filter by tag")] = None,
    group_id: Annotated[Optional[UUID], Query(description="Filter by author group")] = None,
    search: Annotated[Optional[str], Query(description="Search by plan title")] = None,
    language: Annotated[
        str,
        Query(description="Filter by language code (e.g., 'bo', 'en', 'zh'). Defaults to 'en'."),
    ] = "en",
    sort_by: Annotated[str, Query(enum=["title", "total_days", "subscription_count"])] = "title",
    sort_order: Annotated[str, Query(enum=["asc", "desc"])] = "asc",
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone (e.g. Asia/Shanghai). Restricted plans are hidden for Chinese timezones."),
    ] = None,
):
    return await get_published_plans(
        tag=tag,
        group_id=group_id,
        search=search,
        language=language,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
        timezone_name=x_timezone,
    )


@public_plans_router.get(
    "/tags", status_code=status.HTTP_200_OK, response_model=TagsResponse
)
def get_plan_tags(
    language: Annotated[
        str,
        Query(description="Filter by language code (e.g., 'bo', 'en', 'zh'). Defaults to 'en'."),
    ] = "en",
):
    return get_tags(language=language)


@public_plans_router.get("/{plan_id}", status_code=status.HTTP_200_OK, response_model=PublicPlanDTO)
async def get_plan_details(
    plan_id: UUID,
    x_timezone: Annotated[
        Optional[str],
        Header(alias="X-Timezone", description="IANA timezone (e.g. Asia/Shanghai). Restricted plans are hidden for Chinese timezones."),
    ] = None,
):
    return await get_published_plan(plan_id=plan_id, timezone_name=x_timezone)


@public_plans_router.get("/{plan_id}/daily", status_code=status.HTTP_200_OK, response_model=DailyPlanResponse)
async def get_plan_daily(
    plan_id: UUID,
    date: Annotated[
        Optional[DateType],
        Query(description="Date in YYYY-MM-DD format. Defaults to today if not provided."),
    ] = None,
    language: Annotated[
        Optional[str],
        Query(description=language_query_description("Filter series navigation and metadata by language", lowercase_example=True)),
    ] = None,
):
    return await get_plan_daily_content(plan_id=plan_id, requested_date=date, language=language)


@public_plans_router.delete(
    "/{plan_id}/cache/plan-days",
    status_code=status.HTTP_200_OK,
    response_model=PlanDayCacheCleanupResponse,
)
async def cleanup_plan_days_cache(plan_id: UUID):
    """Invalidate cached public plan day responses for every day in a plan (DEBUG only)."""
    _require_debug_deployment_mode()
    with SessionLocal() as db:
        keys_deleted = await invalidate_all_plan_day_detail_caches_for_plan(db=db, plan_id=plan_id)
    return PlanDayCacheCleanupResponse(plan_id=plan_id, keys_deleted=keys_deleted)


@public_plans_router.delete(
    "/{plan_id}/days/{day_number}/cache",
    status_code=status.HTTP_200_OK,
    response_model=PlanDayCacheCleanupResponse,
)
async def cleanup_plan_day_cache(plan_id: UUID, day_number: int):
    """Invalidate the cached public plan day response for one day (DEBUG only)."""
    _require_debug_deployment_mode()
    keys_deleted = await invalidate_plan_day_detail_cache(plan_id=plan_id, day_number=day_number)
    return PlanDayCacheCleanupResponse(
        plan_id=plan_id,
        day_number=day_number,
        keys_deleted=keys_deleted,
    )


@public_plans_router.get("/{plan_id}/days", status_code=status.HTTP_200_OK, response_model=PlanDaysResponse)
async def get_plan_days_list(
    plan_id: UUID,
    credentials: Annotated[Optional[HTTPAuthorizationCredentials], Depends(optional_oauth2_scheme)]
):
    user_id = None
    if credentials:
        try:
            user = await run_in_threadpool(
                validate_and_extract_user_details, token=credentials.credentials
            )
            user_id = user.id
        except Exception:
            pass

    # Enrollment is a synchronous DB transaction; keep it off the event loop.
    await run_in_threadpool(auto_enroll_plan, plan_id=plan_id, user_id=user_id)
    return await get_plan_days(plan_id=plan_id)


@public_plans_router.get("/{plan_id}/days/{day_number}", status_code=status.HTTP_200_OK, response_model=PlanDayDTO)
async def get_plan_day_content(plan_id: UUID, day_number: int):
    """Get specific day's content with tasks"""
    return await get_plan_day_details(plan_id=plan_id, day_number=day_number)
