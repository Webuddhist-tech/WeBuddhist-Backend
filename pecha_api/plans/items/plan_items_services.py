from uuid import UUID
from typing import List, Optional, Tuple
from datetime import datetime
from fastapi import HTTPException
from sqlalchemy.orm import Session
from starlette import status
from pecha_api.plans.auth.plan_auth_models import ResponseError
from pecha_api.plans.response_message import BAD_REQUEST, PLAN_NOT_FOUND, DUPLICATE_DAY_NUMBERS, PLAN_DAY_NOT_FOUND, PLAN_AUTHOR_MISMATCH, PLAN_DAYS_OVERLAP_NEXT_PLAN
from .plan_items_repository import (
    save_plan_item,
    save_plan_items,
    get_last_day_number,
    delete_days_by_ids,
    get_days_by_plan_id,
    get_days_by_plan_id_and_day_ids,
    update_days_in_bulk_by_plan_id,
    get_plan_day_by_id_with_tasks_and_subtasks,
    get_plan_day_by_id_any_plan,
)
from pecha_api.plans.cms.cms_plans_repository import get_plan_by_id, get_next_series_plan_start_date
from pecha_api.plans.cms.cms_plans_service import shift_subsequent_series_plans
from .plan_items_models import PlanItem
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.authors.plan_authors_model import Author
from .plan_items_response_models import ItemDTO, ReorderDaysRequest, CreateDaysRequest, DeleteDaysRequest, ItemDayNumberDTO
from pecha_api.plans.authors.plan_authors_service import validate_cms_author_details
from pecha_api.plans.shared.permissions import require_can_edit_content, require_can_read_group_content
from pecha_api.plans.tasks.plan_tasks_models import PlanTask
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_models import PlanSubTask
from pecha_api.plans.audio.sub_task_timestamps_models import SubTaskTimestamp
from pecha_api.db.database import SessionLocal


def _get_series_schedule_overflow(
    db: Session, plan: Plan, last_day_number: int, number_of_days: int
) -> Optional[Tuple[int, datetime]]:
    """Return (overflow_days, next_plan_start_date) if adding number_of_days would reach or
    pass the next series plan's start date, else None."""
    if plan.series_id is None or plan.start_date is None or plan.display_order is None:
        return None

    next_plan_start_date = get_next_series_plan_start_date(
        db=db,
        series_id=plan.series_id,
        display_order=plan.display_order,
    )
    if next_plan_start_date is None:
        return None

    available_days = (next_plan_start_date.date() - plan.start_date.date()).days - last_day_number
    overflow_days = number_of_days - available_days
    if overflow_days <= 0:
        return None
    return overflow_days, next_plan_start_date


def _validate_days_within_series_schedule(
    db: Session, plan: Plan, last_day_number: int, number_of_days: int, cascade: bool, author: Author
) -> None:
    overflow = _get_series_schedule_overflow(
        db=db, plan=plan, last_day_number=last_day_number, number_of_days=number_of_days
    )
    if overflow is None:
        return

    overflow_days, next_plan_start_date = overflow
    if not cascade:
        available_days = number_of_days - overflow_days
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                **ResponseError(
                    error=BAD_REQUEST,
                    message=PLAN_DAYS_OVERLAP_NEXT_PLAN.format(
                        next_start_date=next_plan_start_date.date().isoformat(),
                        available_days=max(available_days, 0),
                    ),
                ).model_dump(),
                "code": "PLAN_DAYS_OVERLAP_NEXT_PLAN",
                "overflow_days": overflow_days,
                "next_plan_start_date": next_plan_start_date.date().isoformat(),
            },
        )

    shift_subsequent_series_plans(db=db, plan=plan, shift_days=overflow_days, author=author)


def create_plan_item(token: str, plan_id: UUID, create_days_request: CreateDaysRequest) -> List[ItemDTO]:
    current_author = validate_cms_author_details(token=token)

    with SessionLocal() as db_session:
        plan = _get_author_plan(db=db_session, plan_id=plan_id, current_author=current_author)
        last_day_number = get_last_day_number(db=db_session, plan_id=plan.id)

        _validate_days_within_series_schedule(
            db=db_session,
            plan=plan,
            last_day_number=last_day_number,
            number_of_days=create_days_request.number_of_days,
            cascade=create_days_request.cascade,
            author=current_author,
        )

        source_day = None
        if create_days_request.source_day_id:
            source_day = get_plan_day_by_id_any_plan(
                db=db_session,
                day_id=create_days_request.source_day_id,
            )
            # Verify author can access the source plan
            source_plan = get_plan_by_id(db=db_session, plan_id=source_day.plan_id)
            if not source_plan:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=ResponseError(error=BAD_REQUEST, message="Source plan not found").model_dump(),
                )
            require_can_read_group_content(
                db=db_session,
                group_id=source_plan.group_id,
                author=current_author,
            )

        new_plan_items = [
            PlanItem(
                plan_id=plan.id,
                day_number=last_day_number + offset,
                created_by=current_author.email,
            )
            for offset in range(1, create_days_request.number_of_days + 1)
        ]

        try:
            saved_items = save_plan_items(db=db_session, plan_items=new_plan_items, commit=False)

            if source_day is not None:
                _copy_tasks_and_subtasks_to_days(
                    db=db_session,
                    source_day=source_day,
                    target_days=saved_items,
                    created_by=current_author.email,
                )

            db_session.commit()
        except HTTPException:
            db_session.rollback()
            raise
        except Exception as e:
            db_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ResponseError(error=BAD_REQUEST, message=str(e)).model_dump(),
            ) from e

        for saved_item in saved_items:
            db_session.refresh(saved_item)

        created_days = [
            ItemDTO(
                id=saved_item.id,
                plan_id=saved_item.plan_id,
                day_number=saved_item.day_number,
            )
            for saved_item in saved_items
        ]

    return created_days


def delete_plan_days(token: str, plan_id: UUID, delete_days_request: DeleteDaysRequest) -> None:
    if not delete_days_request.day_ids:
        return

    current_author = validate_cms_author_details(token=token)

    with SessionLocal() as db_session:
        plan = _get_author_plan(db=db_session, plan_id=plan_id, current_author=current_author)

        unique_day_ids = list(dict.fromkeys(delete_days_request.day_ids))
        days = get_days_by_plan_id_and_day_ids(db=db_session, plan_id=plan.id, day_ids=unique_day_ids)
        if len(days) != len(unique_day_ids):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=ResponseError(error=BAD_REQUEST, message=PLAN_DAY_NOT_FOUND).model_dump(),
            )

        try:
            delete_days_by_ids(db=db_session, plan_id=plan.id, day_ids=unique_day_ids, commit=False)
            _reorder_day_display_order(db=db_session, plan_id=plan.id, commit=False)
            db_session.commit()
        except HTTPException:
            db_session.rollback()
            raise
        except Exception as e:
            db_session.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=ResponseError(error=BAD_REQUEST, message=str(e)).model_dump(),
            ) from e


def update_plans_day_number(token: str, plan_id: UUID, reorder_days_request: ReorderDaysRequest) -> None:
    current_author = validate_cms_author_details(token=token)
    with SessionLocal() as db_session:
        plan = _get_author_plan(db=db_session, plan_id=plan_id, current_author=current_author)
        _check_duplicate_day_number_payload(payload=reorder_days_request)
        update_days_in_bulk_by_plan_id(db=db_session, plan_id=plan.id, days=reorder_days_request.days)


def _reorder_day_display_order(db: Session, plan_id: UUID, *, commit: bool = True) -> None:
    items = get_days_by_plan_id(db=db, plan_id=plan_id)
    sorted_items = sorted(items, key=lambda x: x.day_number)
    changes = [
        (item, index)
        for index, item in enumerate(sorted_items, start=1)
        if item.day_number != index
    ]
    if not changes:
        return

    # Two-phase update avoids unique-constraint conflicts when shifting day numbers down.
    temp_updates = [
        ItemDayNumberDTO(id=item.id, day_number=-index)
        for item, index in changes
    ]
    update_days_in_bulk_by_plan_id(db=db, plan_id=plan_id, days=temp_updates, commit=False)

    final_updates = [
        ItemDayNumberDTO(id=item.id, day_number=index)
        for item, index in changes
    ]
    update_days_in_bulk_by_plan_id(db=db, plan_id=plan_id, days=final_updates, commit=commit)


def _get_author_plan(db: Session, plan_id: UUID, current_author: Author) -> Plan:
    plan = get_plan_by_id(db=db, plan_id=plan_id)
    if not plan or plan.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=ResponseError(error=BAD_REQUEST, message=PLAN_NOT_FOUND).model_dump(),
        )
    require_can_edit_content(
        db=db,
        group_id=plan.group_id,
        author=current_author,
        content_status=plan.status,
    )
    return plan


def _check_duplicate_day_number_payload(payload: ReorderDaysRequest) -> None:
    day_numbers = {day.day_number for day in payload.days}
    if len(day_numbers) != len(payload.days):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=ResponseError(error=BAD_REQUEST, message=DUPLICATE_DAY_NUMBERS).model_dump(),
        )


def _copy_tasks_and_subtasks_to_days(
    db: Session,
    source_day: PlanItem,
    target_days: List[PlanItem],
    created_by: str,
) -> None:
    source_tasks = sorted(source_day.tasks, key=lambda task: task.display_order)
    if not source_tasks:
        return

    for target_day in target_days:
        for source_task in source_tasks:
            new_task = PlanTask(
                plan_item_id=target_day.id,
                title=source_task.title,
                display_order=source_task.display_order,
                estimated_time=source_task.estimated_time,
                is_required=source_task.is_required,
                # Reader defaults carry over; live does not - it belongs to one day.
                is_commentary_open=source_task.is_commentary_open,
                commentary_text_id=source_task.commentary_text_id,
                is_translation_open=source_task.is_translation_open,
                translation_text_id=source_task.translation_text_id,
                created_by=created_by,
            )
            db.add(new_task)
            db.flush()

            for source_sub_task in sorted(source_task.sub_tasks, key=lambda sub_task: sub_task.display_order):
                new_sub_task = PlanSubTask(
                    task_id=new_task.id,
                    content_type=source_sub_task.content_type,
                    content=source_sub_task.content,
                    duration=source_sub_task.duration,
                    source_text_id=source_sub_task.source_text_id,
                    pecha_segment_id=source_sub_task.pecha_segment_id,
                    segment_ids=source_sub_task.segment_ids,
                    segment_numbers=source_sub_task.segment_numbers,
                    display_order=source_sub_task.display_order,
                    created_by=created_by,
                )
                db.add(new_sub_task)
                db.flush()

                if source_sub_task.timestamp:
                    db.add(
                        SubTaskTimestamp(
                            sub_task_id=new_sub_task.id,
                            start_ms=source_sub_task.timestamp.start_ms,
                            end_ms=source_sub_task.timestamp.end_ms,
                            created_by=created_by,
                        )
                    )
