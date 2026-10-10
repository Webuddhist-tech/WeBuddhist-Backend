"""The texts an event's plan recites: the controller's one-tap choices."""

import asyncio
import logging
from typing import Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from pecha_api.db.database import SessionLocal
from pecha_api.plans.items.plan_items_models import PlanItem
from pecha_api.plans.plans_enums import ContentType
from pecha_api.plans.plans_models import Plan
from pecha_api.plans.tasks.plan_tasks_models import PlanTask
from pecha_api.plans.tasks.sub_tasks.plan_sub_tasks_models import PlanSubTask

from .live_control_response_models import PlanTextDTO, PlanTextsResponse
from .live_control_service import load_event_or_404

logger = logging.getLogger(__name__)

# (text_id, plan_id, day_number, display_order)
_Row = Tuple[str, UUID, int, int]


def _event_plan_ids(db: Session, event_id: UUID) -> Tuple[Optional[UUID], Optional[UUID], List[UUID]]:
    """The event's plan, or else every live plan of its series in series order."""
    event = load_event_or_404(db, event_id)
    if event.plan_id is not None:
        plan = db.get(Plan, event.plan_id)
        live = plan is not None and plan.deleted_at is None
        return event.plan_id, None, [event.plan_id] if live else []
    if event.series_id is not None:
        plans = db.execute(
            select(Plan.id)
            .where(Plan.series_id == event.series_id, Plan.deleted_at.is_(None))
            .order_by(Plan.display_order.is_(None), Plan.display_order, Plan.created_at)
        ).scalars()
        return None, event.series_id, list(plans)
    return None, None, []


def _source_rows(db: Session, plan_ids: List[UUID]) -> List[_Row]:
    """Every source text in the plans, in reading order: plan, day, task,
    subtask. Repeats are dropped, each text kept where it first appears."""
    if not plan_ids:
        return []
    plan_rank = {plan_id: rank for rank, plan_id in enumerate(plan_ids)}
    rows = db.execute(
        select(
            PlanSubTask.source_text_id,
            PlanItem.plan_id,
            PlanItem.day_number,
            PlanTask.display_order,
            PlanSubTask.display_order,
        )
        .join(PlanTask, PlanSubTask.task_id == PlanTask.id)
        .join(PlanItem, PlanTask.plan_item_id == PlanItem.id)
        .where(
            PlanItem.plan_id.in_(plan_ids),
            PlanTask.deleted_at.is_(None),
            PlanSubTask.deleted_at.is_(None),
            PlanSubTask.content_type == ContentType.SOURCE_REFERENCE,
            PlanSubTask.source_text_id.isnot(None),
        )
    ).all()
    rows = sorted(rows, key=lambda r: (plan_rank.get(r[1], len(plan_rank)), r[2], r[3], r[4]))

    seen = set()
    texts: List[_Row] = []
    for text_id, plan_id, day_number, _task_order, _subtask_order in rows:
        text_id = (text_id or "").strip()
        if not text_id or text_id in seen:
            continue
        seen.add(text_id)
        texts.append((text_id, plan_id, day_number, len(texts) + 1))
    return texts


async def _title_and_language(text_id: str) -> Tuple[Optional[str], Optional[str]]:
    """Best effort: a text the library cannot name is still offered, untitled."""
    # Imported here: the texts package is heavy and only this needs it.
    from pecha_api.texts.texts_openpecha_service import (
        get_text_versions_by_edition_from_openpecha,
    )

    try:
        response = await get_text_versions_by_edition_from_openpecha(edition_id=text_id, limit=1)
    except Exception:
        logger.info("No title for plan text %s", text_id, exc_info=True)
        return None, None
    text = response.text
    if text is None:
        return None, None
    return text.title or None, (text.language or "").lower() or None


async def get_plan_texts(event_id: UUID) -> PlanTextsResponse:
    def read() -> Tuple[Optional[UUID], Optional[UUID], List[_Row]]:
        with SessionLocal() as db:
            plan_id, series_id, plan_ids = _event_plan_ids(db, event_id)
            return plan_id, series_id, _source_rows(db, plan_ids)

    plan_id, series_id, rows = await run_in_threadpool(read)
    names: Dict[str, Tuple[Optional[str], Optional[str]]] = dict(
        zip(
            [row[0] for row in rows],
            await asyncio.gather(*[_title_and_language(row[0]) for row in rows]),
        )
    )
    return PlanTextsResponse(
        event_id=event_id,
        plan_id=plan_id,
        series_id=series_id,
        texts=[
            PlanTextDTO(
                text_id=text_id,
                title=names[text_id][0],
                language=names[text_id][1],
                plan_id=row_plan_id,
                day_number=day_number,
                display_order=display_order,
            )
            for text_id, row_plan_id, day_number, display_order in rows
        ],
    )
