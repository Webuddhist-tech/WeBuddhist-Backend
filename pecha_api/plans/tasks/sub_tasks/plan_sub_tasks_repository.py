from typing import List
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from starlette import status

from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.plans.response_message import BAD_REQUEST
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_models import PlanSubTask
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_response_model import SubTaskDTO


def get_max_display_order_for_sub_task(db: Session, task_id: UUID) -> int:
    max_order = (
        db.query(func.max(PlanSubTask.display_order))
        .filter(PlanSubTask.task_id == task_id)
        .scalar()
        or 0
    )
    return int(max_order)


def save_sub_tasks_bulk(db: Session, sub_tasks: List[PlanSubTask]) -> List[PlanSubTask]:
    if not sub_tasks:
        return []
    try:
        db.add_all(sub_tasks)
        db.commit()
        return sub_tasks
    except IntegrityError as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ResponseError(error=BAD_REQUEST, message=str(e.orig)).model_dump(),
        )

def get_sub_task_by_id(db: Session, sub_task_id: UUID, task_id: UUID) -> PlanSubTask:
    return db.query(PlanSubTask).filter(PlanSubTask.id == sub_task_id, PlanSubTask.task_id == task_id).first()

def get_sub_task_by_subtask_id(db: Session, id: UUID) -> PlanSubTask:
    return db.query(PlanSubTask).filter(PlanSubTask.id == id).first()

def get_sub_tasks_by_task_id(db: Session, task_id: UUID) -> List[PlanSubTask]:
    return db.query(PlanSubTask).filter(PlanSubTask.task_id == task_id).order_by(PlanSubTask.display_order).all()

def delete_sub_tasks_bulk(db: Session, sub_tasks_ids: List[UUID]) -> None:
    if not sub_tasks_ids:
        return
    db.query(PlanSubTask).filter(PlanSubTask.id.in_(sub_tasks_ids)).delete()
    db.commit()

def update_sub_tasks_bulk(db: Session, task_id: UUID, sub_tasks: List[SubTaskDTO]) -> None:
    """Update subtasks in place, scoped to the task the caller was authorized for.

    `task_id` is part of the predicate, not just a lookup hint: authorization
    is granted for one task, so a subtask id belonging to another task must
    not be writable through this call.
    """
    if not sub_tasks:
        return
    for sub_task in sub_tasks:
        db.query(PlanSubTask).filter(
            PlanSubTask.id == sub_task.id,
            PlanSubTask.task_id == task_id,
        ).update(
            {
                PlanSubTask.content: sub_task.content,
                PlanSubTask.content_type: sub_task.content_type,
                PlanSubTask.duration: sub_task.duration,
                PlanSubTask.source_text_id: sub_task.source_text_id,
                PlanSubTask.pecha_segment_id: sub_task.pecha_segment_id,
                PlanSubTask.segment_ids: sub_task.segment_ids,
                PlanSubTask.segment_numbers: sub_task.segment_numbers,
                PlanSubTask.reference_id: sub_task.reference_id,
                PlanSubTask.display_order: sub_task.display_order,
            },
            synchronize_session=False,
        )
    db.commit()

def update_sub_task_order(db: Session, sub_task: PlanSubTask) -> PlanSubTask:
    db.commit()
    db.refresh(sub_task)
    return sub_task

def update_sub_task_order_in_bulk_by_task_id(db: Session, sub_task_list: List[PlanSubTask], task_id: UUID) -> List[PlanSubTask]:
    try:
        db.execute(update(PlanSubTask).where(PlanSubTask.task_id == task_id).execution_options(synchronize_session=False), sub_task_list)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=ResponseError(error=BAD_REQUEST, message=str(e)).model_dump())

def update_sub_tasks(db: Session) -> None:
    db.commit()