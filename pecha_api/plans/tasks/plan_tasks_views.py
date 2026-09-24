from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_invalidation_deps import invalidate_on_write
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import APIRouter, Depends, Query
from typing import Annotated
from uuid import UUID
from starlette import status
from pecha_api.plans.tasks.plan_tasks_response_model import CreateTaskRequest, TaskDTO, UpdateTaskDayRequest, UpdatedTaskDayResponse, GetTaskResponse, UpdateTaskOrderRequest, UpdatedTaskOrderResponse, UpdateTaskTitleRequest, UpdateTaskTitleResponse
from pecha_api.plans.tasks.plan_tasks_services import create_new_task, change_task_day_service, delete_task_by_id, get_task_subtasks_service, change_task_order_service, update_task_title_service

oauth2_scheme = HTTPBearer()
# Create router for plan endpoints
plans_router = APIRouter(
    prefix="/cms/tasks",
    tags=["CMS Tasks"],
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


@plans_router.post("", status_code=status.HTTP_201_CREATED, response_model=TaskDTO)
async def create_task(
        authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
        create_task_request: CreateTaskRequest,
):
    new_task: TaskDTO = await create_new_task(
        token=authentication_credential.credentials,
        create_task_request=create_task_request,
        plan_id=create_task_request.plan_id,
        day_id=create_task_request.day_id,
    )
    return new_task

@plans_router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_task(
    task_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    await delete_task_by_id(
        task_id=task_id,
        token=authentication_credential.credentials
    )   

@plans_router.patch("/{task_id}", response_model=UpdatedTaskDayResponse)
async def change_task_day(
        authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
        task_id: UUID,
        update_task_request: UpdateTaskDayRequest,
)-> UpdatedTaskDayResponse:
    return await change_task_day_service(
        token=authentication_credential.credentials,
        task_id=task_id,
        update_task_request=update_task_request,
    )

@plans_router.put("/{task_id}", response_model=UpdateTaskTitleResponse)
async def update_task_title(
    task_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    update_request: UpdateTaskTitleRequest,
) -> UpdateTaskTitleResponse:

    return await update_task_title_service(
        token=authentication_credential.credentials,
        task_id=task_id,
        update_request=update_request,
    )

@plans_router.put("/{day_id}/order", status_code=status.HTTP_204_NO_CONTENT)
async def change_task_order(
    day_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
    update_task_order_request: UpdateTaskOrderRequest,
):    
    return await change_task_order_service(
        token=authentication_credential.credentials,
        day_id=day_id,
        update_task_order_request=update_task_order_request,
    )

@plans_router.get("/{task_id}", response_model=GetTaskResponse)
async def get_task(
    task_id: UUID,
    authentication_credential: Annotated[HTTPAuthorizationCredentials, Depends(oauth2_scheme)],
):
    return await get_task_subtasks_service(
        task_id=task_id,
        token=authentication_credential.credentials
    )