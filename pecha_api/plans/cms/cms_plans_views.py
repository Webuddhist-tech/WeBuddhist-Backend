from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_invalidation_deps import invalidate_on_write
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import APIRouter, Depends,Query
from typing import Optional
from uuid import UUID
from starlette import status
from typing import Annotated

from pecha_api.plans.plans_response_models import PlansResponse, PlanDTO, CreatePlanRequest, PlanWithDays, UpdatePlanRequest, \
    PlanStatusUpdate, PlanDayDTO, GeneratePlanAudioRequest
from pecha_api.plans.cms.cms_plans_service import get_filtered_plans, create_new_plan, get_details_plan, update_plan_details, \
    delete_selected_plan, update_plan_featured_service, update_selected_plan_status, get_plan_day_details
from pecha_api.plans.plans_enums import SortBy, SortOrder
from pecha_api.plans.audio.cms_plan_audio_service import get_cms_plan_audio_list
from pecha_api.plans.audio.plan_audio_response_models import (
    PlanAudioListResponse,
    AudioJobAcceptedResponse,
    AudioJobStatusResponse,
)
from pecha_api.plans.audio.audio_job_service import enqueue_plan_audio_job, get_audio_job_status
from pecha_api.plans.videos.plan_video_service import (
    add_plan_video,
    list_plan_videos,
    remove_plan_video,
    reorder_plan_videos_entries,
)
from pecha_api.plans.videos.plan_video_response_models import (
    CreatePlanVideoRequest,
    PlanVideoDTO,
    PlanVideoListResponse,
    ReorderPlanVideosRequest,
)

oauth2_scheme = HTTPBearer()
# Create router for CMS plan endpoints
cms_plans_router = APIRouter(
    prefix="/cms/plans",
    tags=["CMS Plans"],
    # Every write on this router clears the namespaces it can affect.
    dependencies=[Depends(invalidate_on_write(
        CacheType.PLAN_LIST,
        CacheType.PLAN_DETAIL,
        CacheType.PLAN_DAYS_LIST,
        CacheType.PLAN_DAILY,
        CacheType.PLAN_DAY_DETAIL,
        CacheType.SERIES_LIST,
        CacheType.SERIES_FEATURED,
        CacheType.SERIES_DETAIL,
    ))],
)


@cms_plans_router.get("", status_code=status.HTTP_200_OK, response_model=PlansResponse)
def get_plans(
        authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
        search: Annotated[Optional[str], Query(description="Search by plan title")] = None,
        language: Annotated[Optional[str], Query(description="Filter by language code (e.g., 'bo', 'en', 'zh')")] = None,
        sort_by: Annotated[str, Query()] = SortBy.TOTAL_DAYS,
        sort_order: Annotated[str, Query()] = SortOrder.ASC,
        skip: Annotated[int, Query()] = 0,
        limit: Annotated[int, Query()] = 10,
):
    return get_filtered_plans(
        token=authentication_credential.credentials,
        search=search,
        sort_by=sort_by,
        sort_order=sort_order,
        skip=skip,
        limit=limit,
        language=language
    )


@cms_plans_router.post("", status_code=status.HTTP_201_CREATED, response_model=PlanDTO)
async def create_plan(authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
                      create_plan_request: CreatePlanRequest):
    return create_new_plan(
        token=authentication_credential.credentials,
        create_plan_request=create_plan_request
    )


@cms_plans_router.get("/audio", status_code=status.HTTP_200_OK, response_model=PlanAudioListResponse)
async def list_plan_audio(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    search: Annotated[Optional[str], Query(description="Search by audio file name or S3 key")] = None,
    plan_id: Annotated[Optional[UUID], Query(description="Filter audio by plan id")] = None,
    skip: Annotated[int, Query()] = 0,
    limit: Annotated[int, Query()] = 10,
):
    return get_cms_plan_audio_list(
        token=authentication_credential.credentials,
        search=search,
        plan_id=plan_id,
        skip=skip,
        limit=limit,
    )

@cms_plans_router.post(
    "/audio/generate",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=AudioJobAcceptedResponse,
)
async def generate_plan_audio(
    request: GeneratePlanAudioRequest,
):
    return enqueue_plan_audio_job(
        day_id=request.day_id,
        sub_task_id=request.sub_task_id,
        language=request.language,
        audio_type=request.type,
        voice_name=request.voice_name,
    )


@cms_plans_router.get(
    "/audio/jobs/{job_id}",
    status_code=status.HTTP_200_OK,
    response_model=AudioJobStatusResponse,
)
async def get_plan_audio_job_status(
    job_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    _ = authentication_credential
    return get_audio_job_status(job_id=job_id)


@cms_plans_router.get("/{plan_id}", status_code=status.HTTP_200_OK, response_model=PlanWithDays)
async def get_plan_details(authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
                           plan_id: UUID):
    return await get_details_plan(
        token=authentication_credential.credentials,
        plan_id=plan_id
    )


@cms_plans_router.put("/{plan_id}", status_code=status.HTTP_200_OK, response_model=PlanDTO)
async def update_plan(authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
                      plan_id: UUID, update_plan_request: UpdatePlanRequest = None):
    return await update_plan_details(
        token=authentication_credential.credentials,
        plan_id=plan_id,
        update_plan_request=update_plan_request
    )


@cms_plans_router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan(authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
                      plan_id: UUID):
    return await delete_selected_plan(
        token=authentication_credential.credentials,
        plan_id=plan_id
    )


@cms_plans_router.patch("/{plan_id}/status", status_code=status.HTTP_200_OK, response_model=PlanDTO)
async def update_plan_status(
        authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
        plan_id: UUID,
        plan_status_update: PlanStatusUpdate = None
):
    return await update_selected_plan_status(
        token=authentication_credential.credentials,
        plan_id=plan_id,
        plan_status_update=plan_status_update
    )

@cms_plans_router.get("/{plan_id}/days/{day_number}", status_code=status.HTTP_200_OK, response_model=PlanDayDTO)
async def get_plan_day_content(authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
                           plan_id: UUID, day_number: int):
    return await get_plan_day_details(
        token=authentication_credential.credentials,
        plan_id=plan_id,
        day_number=day_number
    )


@cms_plans_router.patch("/{plan_id}/featured", status_code=status.HTTP_204_NO_CONTENT)
def update_plan_featured(authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
                              plan_id: UUID):
    return update_plan_featured_service(
        token=authentication_credential.credentials,
        plan_id=plan_id,
    )


@cms_plans_router.get("/{plan_id}/videos", status_code=status.HTTP_200_OK, response_model=PlanVideoListResponse)
async def get_plan_videos(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    plan_id: UUID,
):
    return list_plan_videos(
        token=authentication_credential.credentials,
        plan_id=plan_id,
    )


@cms_plans_router.post("/{plan_id}/videos", status_code=status.HTTP_201_CREATED, response_model=PlanVideoDTO)
async def create_plan_video(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    plan_id: UUID,
    create_video_request: CreatePlanVideoRequest,
):
    return add_plan_video(
        token=authentication_credential.credentials,
        plan_id=plan_id,
        request=create_video_request,
    )


@cms_plans_router.put("/{plan_id}/videos/order", status_code=status.HTTP_200_OK, response_model=PlanVideoListResponse)
async def reorder_plan_videos(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    plan_id: UUID,
    reorder_videos_request: ReorderPlanVideosRequest,
):
    return reorder_plan_videos_entries(
        token=authentication_credential.credentials,
        plan_id=plan_id,
        request=reorder_videos_request,
    )


@cms_plans_router.delete("/{plan_id}/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_plan_video(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    plan_id: UUID,
    video_id: UUID,
):
    return remove_plan_video(
        token=authentication_credential.credentials,
        plan_id=plan_id,
        video_id=video_id,
    )