from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_invalidation_deps import invalidate_on_write
from fastapi import APIRouter, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from typing import Annotated
from uuid import UUID
from starlette import status

from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_response_model import (SubTaskRequest, SubTaskResponse, UpdateSubTaskRequest, SubTaskOrderRequest, SubTaskOrderResponse)
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_services import (create_new_sub_tasks, update_sub_task_by_task_id, change_subtask_order_service)
from pecha_api.plans.audio.plan_subtask_audio_service import delete_plan_subtask_audio
from pecha_api.plans.audio.timestamp_service import delete_plan_subtask_timestamp

sub_tasks_router = APIRouter(
    prefix="/cms/sub-tasks",
    tags=["CMS Sub Tasks"],
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

oauth2_scheme = HTTPBearer()

@sub_tasks_router.post("", status_code=status.HTTP_201_CREATED, response_model=SubTaskResponse)
async def create_sub_tasks(
        authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
        create_task_request: SubTaskRequest,
):
    return await create_new_sub_tasks(
        token=authentication_credential.credentials,
        create_task_request=create_task_request,
    )

@sub_tasks_router.put("", status_code=status.HTTP_204_NO_CONTENT)
async def update_sub_task(
        authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
        update_sub_task_request: UpdateSubTaskRequest,
):
    return await update_sub_task_by_task_id(
        token=authentication_credential.credentials,
        update_sub_task_request=update_sub_task_request,
    )

@sub_tasks_router.put("/{task_id}/order", status_code=status.HTTP_204_NO_CONTENT)
async def change_subtask_order(
    task_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    update_subtask_order_request: SubTaskOrderRequest,
):
    return await change_subtask_order_service(
        token=authentication_credential.credentials,
        task_id=task_id,
        update_subtask_order=update_subtask_order_request,
    )


@sub_tasks_router.delete("/{sub_task_id}/audio", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subtask_audio(
    sub_task_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return delete_plan_subtask_audio(
        token=authentication_credential.credentials,
        sub_task_id=sub_task_id,
    )


@sub_tasks_router.delete("/{sub_task_id}/timestamp", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subtask_timestamp(
    sub_task_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return delete_plan_subtask_timestamp(
        token=authentication_credential.credentials,
        sub_task_id=sub_task_id,
    )