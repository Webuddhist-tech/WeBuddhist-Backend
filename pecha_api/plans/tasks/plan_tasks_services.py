import asyncio
from pecha_api.plans.tasks.plan_tasks_repository import save_task, get_task_by_id, delete_task, update_task_day, update_task_title, get_tasks_by_plan_item_id, reorder_day_tasks_display_order, update_task_order, get_tasks_by_plan_item_id
from pecha_api.plans.tasks.plan_tasks_response_model import CreateTaskRequest, TaskDTO, UpdateTaskDayRequest, UpdatedTaskDayResponse, GetTaskResponse, UpdateTaskTitleRequest, UpdateTaskTitleResponse, ContentAndImageUrl, UpdateTaskOrderRequest, UpdatedTaskOrderResponse, TaskOrderItem
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_response_model import SubTaskDTO
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.plans.cms.cms_plans_repository import get_plan_by_id
from pecha_api.plans.shared.permissions import require_can_edit_content, require_can_read_group_content
from uuid import UUID
from fastapi import HTTPException
from pecha_api.db.database import SessionLocal
from pecha_api.plans.items.plan_items_repository import get_plan_item, get_plan_item_by_id
from pecha_api.plans.tasks.plan_tasks_models import PlanTask
from sqlalchemy import func
from typing import List
from pecha_api.plans.authors.plan_authors_model import Author
from fastapi import HTTPException
from starlette import status
from pecha_api.plans.response_message import PLAN_DAY_NOT_FOUND, BAD_REQUEST, TASK_SAME_DAY_NOT_ALLOWED, FORBIDDEN, UNAUTHORIZED_TASK_DELETE, UNAUTHORIZED_TASK_ACCESS, TASK_TITLE_UPDATE_SUCCESS, TASK_NOT_FOUND, TASK_ORDER_UPDATE_FAIL, DUPLICATE_TASK_ORDER
from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.uploads.S3_utils import generate_presigned_access_url
from pecha_api.config import get
from pecha_api.plans.plans_enums import ContentType
from pecha_api.plans.public.plans_cache_service import (
    schedule_invalidate_plan_day_cache_for_day,
    schedule_invalidate_plan_day_cache_for_task,
)
from pecha_api.plans.shared.subtask_content_resolver import resolve_subtasks_content, resolve_subtasks_refs
from pecha_api.plans.shared.subtask_reference_resolver import resolve_subtask_references

def _get_max_display_order(plan_item_id: UUID) -> int:
    with SessionLocal() as db:
        max_order = db.query(func.max(PlanTask.display_order)).filter(PlanTask.plan_item_id == plan_item_id).scalar() or 0
        return max_order

async def create_new_task(token: str, create_task_request: CreateTaskRequest, plan_id: UUID, day_id: UUID) -> TaskDTO:
    current_author = validate_cms_author_details(token=token)

    with SessionLocal() as db:

        plan_item = get_plan_item(db=db, plan_id=plan_id, day_id=day_id)
        plan = get_plan_by_id(db=db, plan_id=plan_id)
        require_can_edit_content(
            db=db,
            group_id=plan.group_id,
            author=current_author,
            content_status=plan.status,
        )
        
        display_order:int = _get_max_display_order(plan_item_id=plan_item.id) + 1

        new_task = PlanTask(
            plan_item_id=plan_item.id,
            title=create_task_request.title,
            display_order=display_order,
            estimated_time=create_task_request.estimated_time,
            created_by=current_author.email,
        )

    saved_task = save_task(db=db,new_task=new_task)

    schedule_invalidate_plan_day_cache_for_day(db=db, day_id=plan_item.id)
    return TaskDTO(
        id=saved_task.id,
        title=saved_task.title,
        display_order=saved_task.display_order,
        estimated_time=saved_task.estimated_time,
    )

async def delete_task_by_id(task_id: UUID, token: str):
    current_author = validate_cms_author_details(token=token)
    
    with SessionLocal() as db:
        task = _get_author_task(db=db, task_id=task_id, current_author=current_author)
        delete_task(db=db, task_id=task.id)

        tasks = get_tasks_by_plan_item_id(db=db, plan_item_id=task.plan_item_id)
        if tasks:
            _reorder_sequentially(db=db, tasks=tasks)
        schedule_invalidate_plan_day_cache_for_task(db=db, task_id=task_id)

async def change_task_day_service(token: str, task_id: UUID, update_task_request: UpdateTaskDayRequest) -> UpdatedTaskDayResponse:
    current_author = validate_cms_author_details(token=token)

    with SessionLocal() as db:
        display_order = _get_max_display_order(plan_item_id=update_task_request.target_day_id) + 1

        targeted_day = get_plan_item_by_id(db=db, day_id=update_task_request.target_day_id)

        if not targeted_day:
            raise HTTPException(status_code=404, detail=ResponseError(error=BAD_REQUEST, message=PLAN_DAY_NOT_FOUND).model_dump())
        
        task = _get_author_task(db=db, task_id=task_id, current_author=current_author)
        source_day_id = task.plan_item_id
        task.plan_item_id = update_task_request.target_day_id
        task.display_order = display_order

        task = update_task_day(
            db=db, 
            updated_task=task
        )

        schedule_invalidate_plan_day_cache_for_day(db=db, day_id=source_day_id)
        schedule_invalidate_plan_day_cache_for_day(db=db, day_id=task.plan_item_id)

        return UpdatedTaskDayResponse(
            task_id=task.id, 
            day_id=task.plan_item_id, 
            display_order=task.display_order, 
            estimated_time=task.estimated_time,
            title=task.title,
        )

async def update_task_title_service(token: str, task_id: UUID, update_request: UpdateTaskTitleRequest) -> UpdateTaskTitleResponse:
    current_author = validate_cms_author_details(token=token)
    
    with SessionLocal() as db:
        task = _get_author_task(db=db, task_id=task_id, current_author=current_author)

        fields_set = update_request.model_fields_set
        if "title" in fields_set:
            task.title = update_request.title
        task.updated_by = current_author.email

        updated_task = update_task_title(db=db, updated_task=task)

        schedule_invalidate_plan_day_cache_for_task(db=db, task_id=task_id)
        return UpdateTaskTitleResponse(
            task_id=updated_task.id,
            title=updated_task.title,
        )


async def change_task_order_service(token: str, day_id: UUID, update_task_order_request: UpdateTaskOrderRequest) -> UpdatedTaskOrderResponse:
    validate_cms_author_details(token=token)

    with SessionLocal() as db:
        _check_duplicate_task_order(update_task_orders=update_task_order_request.tasks)
        update_task_order(db=db, day_id=day_id, update_task_orders=update_task_order_request.tasks)
        schedule_invalidate_plan_day_cache_for_day(db=db, day_id=day_id)


async def get_task_subtasks_service(task_id: UUID, token: str) -> GetTaskResponse:
    current_user = validate_cms_author_details(token=token)

    with SessionLocal() as db:
        task = _get_author_task(db=db, task_id=task_id, current_author=current_user)

        from pecha_api.plans.audio.dto_helpers import build_subtask_timestamp_fields

        resolved_contents, resolved_refs = await asyncio.gather(
            resolve_subtasks_content(task.sub_tasks),
            resolve_subtasks_refs(task.sub_tasks),
        )
        plan_item = get_plan_item_by_id(db=db, day_id=task.plan_item_id)
        plan = get_plan_by_id(db=db, plan_id=plan_item.plan_id) if plan_item else None
        resolved_references = resolve_subtask_references(
            db=db,
            subtasks=task.sub_tasks,
            language=getattr(plan, "language", None),
        )

        subtasks_dto = []
        for sub_task, resolved_content, segment_refs, reference in zip(task.sub_tasks, resolved_contents, resolved_refs, resolved_references):
            content_and_image_url = _generate_image_url_content_type(
                content_type=sub_task.content_type,
                content=resolved_content,
            )
            start_ms, end_ms = build_subtask_timestamp_fields(sub_task)
            audio_url = (
                generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"), s3_key=sub_task.audio_url)
                if sub_task.audio_url else None
            )
            subtasks_dto.append(
                SubTaskDTO(
                    id=sub_task.id,
                    content_type=sub_task.content_type,
                    content=content_and_image_url.content,
                    duration=sub_task.duration,
                    source_text_id=sub_task.source_text_id,
                    pecha_segment_id=sub_task.pecha_segment_id,
                    segment_ids=sub_task.segment_ids,
                    segment_numbers=sub_task.segment_numbers,
                    segment_refs=segment_refs,
                    reference_id=sub_task.reference_id,
                    reference=reference,
                    image_url=content_and_image_url.image_url,
                    audio_url=audio_url,
                    display_order=sub_task.display_order,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            )

        return GetTaskResponse(
            id=task.id,
            title=task.title,
            display_order=task.display_order,
            estimated_time=task.estimated_time,
            subtasks=subtasks_dto,
        )

def _generate_image_url_content_type(content_type: str, content: str) -> ContentAndImageUrl:
    if content_type == ContentType.IMAGE:
        presigned_url = generate_presigned_access_url(
            bucket_name=get("AWS_BUCKET_NAME"), s3_key=content
        )
        return ContentAndImageUrl(content=presigned_url, image_url=content)
    return ContentAndImageUrl(content=content, image_url=None)


def _reorder_sequentially(db: SessionLocal(), tasks: List[PlanTask]):
    
    tasks_to_update: List[PlanTask] = []

    for index, task in enumerate(tasks, start=1):
        if task.display_order != index:
            task.display_order = index
            tasks_to_update.append(task)
    
    if tasks_to_update:
        reorder_day_tasks_display_order(db=db, tasks=tasks_to_update)


def _get_author_task(db: SessionLocal(), task_id: UUID, current_author: Author) -> PlanTask:
    task = get_task_by_id(db=db, task_id=task_id)
    if not task:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ResponseError(error=BAD_REQUEST, message=TASK_NOT_FOUND).model_dump(),
        )
    plan_item = get_plan_item_by_id(db=db, day_id=task.plan_item_id)
    if not plan_item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ResponseError(error=BAD_REQUEST, message=PLAN_DAY_NOT_FOUND).model_dump())
    plan = get_plan_by_id(db=db, plan_id=plan_item.plan_id)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=ResponseError(error=BAD_REQUEST, message=PLAN_DAY_NOT_FOUND).model_dump())
    require_can_edit_content(
        db=db,
        group_id=plan.group_id,
        author=current_author,
        content_status=plan.status,
    )
    return task

def _check_duplicate_task_order(update_task_orders: List[TaskOrderItem]) -> None:
    task_orders = [task_order.display_order for task_order in update_task_orders]
    if len(task_orders) != len(set(task_orders)):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ResponseError(error=BAD_REQUEST, message=DUPLICATE_TASK_ORDER).model_dump())
