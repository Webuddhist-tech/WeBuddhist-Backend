from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_invalidation_deps import invalidate_on_write
from fastapi import APIRouter
from .plan_items_response_models import CreateDaysRequest, DeleteDaysRequest, ItemDTO, ReorderDaysRequest
from .plan_items_services import create_plan_item, delete_plan_days, update_plans_day_number
from pecha_api.plans.audio.plan_day_audio_service import delete_plan_day_audio,assign_plan_day_audio
from pecha_api.plans.shareable_images.day_shareable_image_enums import DayShareableImageType
from pecha_api.plans.shareable_images.day_shareable_image_service import delete_plan_day_shareable_image
from pecha_api.plans.audio.plan_audio_response_models import AssignPlanDayAudioRequest
from pecha_api.plans.media.media_response_models import PlanDayAudioUploadResponse
from pecha_api.plans.videos.day_video_service import (
    add_day_video,
    list_day_videos,
    remove_day_video,
    reorder_day_videos_entries,
)
from pecha_api.plans.videos.day_video_response_models import (
    CreateDayVideoRequest,
    DayVideoDTO,
    DayVideoListResponse,
    ReorderDayVideosRequest,
)
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Depends
from starlette import status
from uuid import UUID
from typing import Annotated, List
oauth2_scheme = HTTPBearer()

items_router = APIRouter(
    prefix="/cms/plans",
    tags=["CMS Items"],
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

@items_router.post("/{plan_id}/days", status_code=status.HTTP_201_CREATED, response_model=List[ItemDTO])
async def create_new_item(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    plan_id: UUID,
    create_days_request: CreateDaysRequest = CreateDaysRequest(),
):
    return create_plan_item(
        token=authentication_credential.credentials,
        plan_id=plan_id,
        create_days_request=create_days_request,
    )

@items_router.delete("/{plan_id}/days", status_code=status.HTTP_204_NO_CONTENT)
async def delete_items(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    plan_id: UUID,
    delete_days_request: DeleteDaysRequest,
):
    return delete_plan_days(
        token=authentication_credential.credentials,
        plan_id=plan_id,
        delete_days_request=delete_days_request,
    )


@items_router.patch("/days/{day_id}/audio", status_code=status.HTTP_200_OK, response_model=PlanDayAudioUploadResponse)
async def assign_day_audio(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    day_id: UUID,
    assign_audio_request: AssignPlanDayAudioRequest,
):
    return assign_plan_day_audio(
        token=authentication_credential.credentials,
        day_id=day_id,
        request=assign_audio_request,
    )


@items_router.delete("/days/{day_id}/audio", status_code=status.HTTP_204_NO_CONTENT)
async def delete_day_audio(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    day_id: UUID,
):
    return delete_plan_day_audio(
        token=authentication_credential.credentials,
        day_id=day_id,
    )


@items_router.delete(
    "/days/{day_id}/shareable-images/{image_type}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_day_shareable_image(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    day_id: UUID,
    image_type: DayShareableImageType,
):
    return delete_plan_day_shareable_image(
        token=authentication_credential.credentials,
        day_id=day_id,
        image_type=image_type,
    )


@items_router.put("/{plan_id}/reorder-days", status_code=status.HTTP_204_NO_CONTENT)
async def reorder_days(authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
                      plan_id: UUID,
                      reorder_days_request: ReorderDaysRequest):
    update_plans_day_number(
        token=authentication_credential.credentials,
        plan_id=plan_id,
        reorder_days_request=reorder_days_request
    )


@items_router.get("/days/{day_id}/videos", status_code=status.HTTP_200_OK, response_model=DayVideoListResponse)
async def get_day_videos(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    day_id: UUID,
):
    return list_day_videos(
        token=authentication_credential.credentials,
        day_id=day_id,
    )


@items_router.post("/days/{day_id}/videos", status_code=status.HTTP_201_CREATED, response_model=DayVideoDTO)
async def create_day_video(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    day_id: UUID,
    create_video_request: CreateDayVideoRequest,
):
    return add_day_video(
        token=authentication_credential.credentials,
        day_id=day_id,
        request=create_video_request,
    )


@items_router.put("/days/{day_id}/videos/order", status_code=status.HTTP_200_OK, response_model=DayVideoListResponse)
async def reorder_day_videos(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    day_id: UUID,
    reorder_videos_request: ReorderDayVideosRequest,
):
    return reorder_day_videos_entries(
        token=authentication_credential.credentials,
        day_id=day_id,
        request=reorder_videos_request,
    )


@items_router.delete("/days/{day_id}/videos/{video_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_day_video(
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    day_id: UUID,
    video_id: UUID,
):
    return remove_day_video(
        token=authentication_credential.credentials,
        day_id=day_id,
        video_id=video_id,
    )