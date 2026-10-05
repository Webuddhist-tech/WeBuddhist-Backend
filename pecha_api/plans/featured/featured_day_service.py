import asyncio
from fastapi import HTTPException, status
from ...db.database import SessionLocal
from .featured_day_repository import get_all_featured_plan_days
from .featured_day_response_model import PlanDayDTO, TaskDTO, SubTaskDTO
from pecha_api.plans.tasks.task_settings_models import build_task_settings
from ...uploads.S3_utils import generate_presigned_access_url
from ...config import get
from ..plans_enums import ContentType
from ..shared.subtask_content_resolver import resolve_subtasks_content
import logging
from datetime import datetime

from ..response_message import NO_FEATURED_PLANS_WITH_DAYS_FOUND


logger = logging.getLogger(__name__)


def generate_subtask_content_url(content_type: ContentType, content: str) -> str:
    if content_type == ContentType.IMAGE:
        return generate_presigned_access_url(bucket_name=get("AWS_BUCKET_NAME"),s3_key=content)
    return content


async def build_task_dto(task) -> TaskDTO:
    ordered_subtasks = sorted(task.sub_tasks, key=lambda st: st.display_order)
    resolved_contents = await resolve_subtasks_content(ordered_subtasks)

    subtasks = [
        SubTaskDTO(
            id=subtask.id,
            content_type=subtask.content_type,
            duration=subtask.duration,
            content=generate_subtask_content_url(subtask.content_type, resolved_content),
            display_order=subtask.display_order
        )
        for subtask, resolved_content in zip(ordered_subtasks, resolved_contents)
    ]

    return TaskDTO(
        id=task.id,
        title=task.title,
        estimated_time=task.estimated_time,
        display_order=task.display_order,
        subtasks=subtasks,
        settings=build_task_settings(task),
    )


async def get_featured_day_service(language: str) -> PlanDayDTO:
    with SessionLocal() as db:
        featured_days = get_all_featured_plan_days(db, language=language.upper())

        if not featured_days:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND,detail=NO_FEATURED_PLANS_WITH_DAYS_FOUND)

        index = datetime.now().date().toordinal() % len(featured_days)
        selected_day_item = featured_days[index]

        tasks = await asyncio.gather(
            *[
                build_task_dto(task)
                for task in sorted(selected_day_item.tasks, key=lambda t: t.display_order)
            ]
        )

        return PlanDayDTO(
            id=selected_day_item.id,
            day_number=selected_day_item.day_number,
            tasks=tasks
        )