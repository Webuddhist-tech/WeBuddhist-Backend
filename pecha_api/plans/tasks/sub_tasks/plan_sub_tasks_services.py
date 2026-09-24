from typing import List
from uuid import UUID

from fastapi import HTTPException
from starlette import status

from pecha_api.db.database import SessionLocal
from pecha_api.plans.tasks.plan_tasks_services import _get_author_task
from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.plans.authors.plan_authors_service import validate_and_extract_author_details
from pecha_api.plans.response_message import BAD_REQUEST, FORBIDDEN, UNAUTHORIZED_TASK_ACCESS, SUBTASK_ORDER_FAILED
from pecha_api.plans.tasks.plan_tasks_repository import get_task_by_id
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_models import PlanSubTask
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_repository import (
    get_max_display_order_for_sub_task,
    save_sub_tasks_bulk,
    get_sub_tasks_by_task_id,
    delete_sub_tasks_bulk,
    update_sub_task_order_in_bulk_by_task_id,
    update_sub_tasks_bulk,
    get_sub_task_by_id,
    update_sub_task_order,
    update_sub_tasks
)

from pecha_api.plans.plans_enums import is_reference_content_type
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_response_model import (
    CONTENT_REQUIRED,
    SubTaskDTO,
    SubTaskRequest,
    SubTaskResponse,
    UpdateSubTaskRequest,
    SubTaskOrderRequest,
    SubTaskOrderResponse
)
from pecha_api.error_contants import ErrorConstants
from pecha_api.plans.response_message import SUBTASK_ORDER_FAILED
from pecha_api.plans.audio.timestamp_service import apply_sub_task_timestamp
from pecha_api.plans.public.plans_cache_service import invalidate_plan_day_cache_for_task
from pecha_api.plans.shared.subtask_content_resolver import resolve_subtasks_content, resolve_subtasks_refs
from pecha_api.plans.shared.subtask_reference_resolver import (
    resolve_subtask_references,
    validate_subtask_reference,
)
from pecha_api.plans.cms.cms_plans_repository import get_plan_by_id
from pecha_api.plans.items.plan_items_repository import get_plan_item_by_id
from pecha_api.plans.response_message import PLAN_DAY_NOT_FOUND, SUBTASK_NOT_IN_TASK
import asyncio


def _get_task_plan(db, task):
    """The plan a task belongs to, which owns the group a subtask may link into."""
    plan_item = get_plan_item_by_id(db=db, day_id=task.plan_item_id)
    plan = get_plan_by_id(db=db, plan_id=plan_item.plan_id) if plan_item else None
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ResponseError(error=BAD_REQUEST, message=PLAN_DAY_NOT_FOUND).model_dump(),
        )
    return plan


def _reject_foreign_sub_task_ids(requested, allowed_ids) -> None:
    """Reject subtask ids that belong to a task the caller wasn't authorized for."""
    allowed = set(allowed_ids)
    if any(sub_task.id not in allowed for sub_task in requested):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ResponseError(error=BAD_REQUEST, message=SUBTASK_NOT_IN_TASK).model_dump(),
        )


def _validate_subtasks(db, plan, sub_tasks) -> None:
    """Check each subtask is coherent for its content type before it is written.

    Inline types must carry content; reference types must instead point at an
    entity in the plan's own group. The request model enforces the content rule
    for creates, but `SubTaskDTO` doubles as a response model and so stays
    lenient - which makes this the only guard on the update path.
    """
    for sub_task in sub_tasks:
        if sub_task.content is None and not is_reference_content_type(
            sub_task.content_type
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ResponseError(
                    error=BAD_REQUEST, message=CONTENT_REQUIRED
                ).model_dump(),
            )
        validate_subtask_reference(
            db=db,
            content_type=sub_task.content_type,
            reference_id=sub_task.reference_id,
            group_id=plan.group_id,
        )

async def create_new_sub_tasks(token: str, create_task_request: SubTaskRequest) -> SubTaskResponse:
    current_author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        task = _get_author_task(db=db, task_id=create_task_request.task_id, current_author=current_author)
        plan = _get_task_plan(db=db, task=task)
        _validate_subtasks(db=db, plan=plan, sub_tasks=create_task_request.sub_tasks)

        next_display_order = get_max_display_order_for_sub_task(db=db, task_id=create_task_request.task_id) + 1

        new_sub_tasks: List[PlanSubTask] = []
        for index, sub in enumerate(create_task_request.sub_tasks, start=0):
            
            new_sub_tasks.append(
                PlanSubTask(
                    task_id=create_task_request.task_id,
                    content_type=sub.content_type,
                    content=sub.content,
                    duration=sub.duration,
                    source_text_id=sub.source_text_id,          
                    pecha_segment_id=sub.pecha_segment_id,
                    segment_ids=sub.segment_ids,
                    segment_numbers=sub.segment_numbers,
                    reference_id=sub.reference_id,
                    display_order=next_display_order + index,
                    created_by=current_author.email,
                )
            )

        saved_sub_tasks = save_sub_tasks_bulk(db=db, sub_tasks=new_sub_tasks)
        resolved_contents, resolved_refs = await asyncio.gather(
            resolve_subtasks_content(saved_sub_tasks),
            resolve_subtasks_refs(saved_sub_tasks),
        )
        resolved_references = resolve_subtask_references(
            db=db, subtasks=saved_sub_tasks, language=plan.language
        )
        created_sub_tasks = []
        for item, sub_request, resolved_content, segment_refs, reference in zip(saved_sub_tasks, create_task_request.sub_tasks, resolved_contents, resolved_refs, resolved_references):
            start_ms, end_ms = apply_sub_task_timestamp(
                db=db,
                sub_task_id=item.id,
                task_id=create_task_request.task_id,
                start_ms=sub_request.start_ms,
                end_ms=sub_request.end_ms,
                author_email=current_author.email,
            )
            created_sub_tasks.append(
                SubTaskDTO(
                    id=item.id,
                    content_type=item.content_type,
                    content=resolved_content,
                    duration=item.duration,
                    source_text_id=item.source_text_id,
                    pecha_segment_id=item.pecha_segment_id,
                    segment_ids=item.segment_ids,
                    segment_numbers=item.segment_numbers,
                    segment_refs=segment_refs,
                    reference_id=item.reference_id,
                    reference=reference,
                    display_order=item.display_order,
                    start_ms=start_ms,
                    end_ms=end_ms,
                )
            )
        await invalidate_plan_day_cache_for_task(db=db, task_id=create_task_request.task_id)
        return SubTaskResponse(
            sub_tasks=created_sub_tasks,
        )

async def update_sub_task_by_task_id(token: str, update_sub_task_request: UpdateSubTaskRequest) -> None:
    current_author = validate_and_extract_author_details(token=token)

    with SessionLocal() as db:
        task = _get_author_task(db=db, task_id=update_sub_task_request.task_id, current_author=current_author)
        plan = _get_task_plan(db=db, task=task)
        _validate_subtasks(db=db, plan=plan, sub_tasks=update_sub_task_request.sub_tasks)

        existing_in_db = get_sub_tasks_by_task_id(db=db, task_id=update_sub_task_request.task_id)
        existing_ids_in_db = [sub_task.id for sub_task in existing_in_db]

        existing_sub_tasks_to_update: List[SubTaskDTO] = [
            subtask for subtask in update_sub_task_request.sub_tasks if subtask.id is not None
        ]

        # Authorization was granted for this task only, so a subtask id from
        # another task must be rejected outright rather than silently skipped.
        _reject_foreign_sub_task_ids(
            requested=existing_sub_tasks_to_update,
            allowed_ids=existing_ids_in_db,
        )

        new_sub_tasks_to_create: List[PlanSubTask] = [
            PlanSubTask(
                task_id=update_sub_task_request.task_id,
                content_type=subtask.content_type,
                content=subtask.content,
                duration=subtask.duration,
                source_text_id=subtask.source_text_id,
                pecha_segment_id=subtask.pecha_segment_id,
                segment_ids=subtask.segment_ids,
                segment_numbers=subtask.segment_numbers,
                reference_id=subtask.reference_id,
                display_order=subtask.display_order,
                created_by=current_author.email,
            )
            for subtask in update_sub_task_request.sub_tasks
            if subtask.id is None
        ]

        requested_existing_ids = [sub_task.id for sub_task in existing_sub_tasks_to_update]
        sub_tasks_ids_to_delete = [id for id in existing_ids_in_db if id not in requested_existing_ids]

        delete_sub_tasks_bulk(db=db, sub_tasks_ids=sub_tasks_ids_to_delete)

        update_sub_tasks_bulk(
            db=db,
            task_id=update_sub_task_request.task_id,
            sub_tasks=existing_sub_tasks_to_update,
        )

        for subtask in existing_sub_tasks_to_update:
            apply_sub_task_timestamp(
                db=db,
                sub_task_id=subtask.id,
                task_id=update_sub_task_request.task_id,
                start_ms=subtask.start_ms,
                end_ms=subtask.end_ms,
                author_email=current_author.email,
            )

        if new_sub_tasks_to_create:
            saved_new = save_sub_tasks_bulk(db=db, sub_tasks=new_sub_tasks_to_create)
            new_requests = [
                subtask
                for subtask in update_sub_task_request.sub_tasks
                if subtask.id is None
            ]
            for saved_item, sub_request in zip(saved_new, new_requests):
                apply_sub_task_timestamp(
                    db=db,
                    sub_task_id=saved_item.id,
                    task_id=update_sub_task_request.task_id,
                    start_ms=sub_request.start_ms,
                    end_ms=sub_request.end_ms,
                    author_email=current_author.email,
                )

        await invalidate_plan_day_cache_for_task(db=db, task_id=update_sub_task_request.task_id)


async def change_subtask_order_service(token: str, task_id: UUID, update_subtask_order: SubTaskOrderRequest) -> None:
    current_author = validate_and_extract_author_details(token=token)
    with SessionLocal() as db:
        task = _get_author_task(db=db, task_id=task_id, current_author=current_author)
        
        update_sub_task_order_in_bulk_by_task_id(db=db, sub_task_list=update_subtask_order.subtasks,task_id=task.id)
        await invalidate_plan_day_cache_for_task(db=db, task_id=task_id)
