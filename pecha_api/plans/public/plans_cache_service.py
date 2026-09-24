import asyncio
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_repository import delete_cache, get_cache_data, set_cache
from pecha_api.plans.items.plan_items_repository import get_days_by_plan_id, get_plan_item_by_id
from pecha_api.plans.public.plan_response_models import PlanDayDTO
from pecha_api.plans.tasks.plan_tasks_repository import get_task_by_id
from pecha_api.utils import Utils


def _plan_timeout() -> int:
    return config.get_int("CACHE_PLAN_TIMEOUT")


def _plan_day_detail_cache_keys(plan_id: UUID, day_number: int) -> list[str]:
    """Build current and legacy Redis hash keys for a plan day."""
    keys = []
    for cache_type in (CacheType.PLAN_DAY_DETAIL, CacheType.PLAN_DAY_DETAIL.value):
        payload = [str(plan_id), day_number, cache_type]
        keys.append(Utils.generate_hash_key(payload=payload))
    return list(dict.fromkeys(keys))


async def get_plan_day_detail_cache(plan_id: UUID, day_number: int) -> Optional[PlanDayDTO]:
    for hashed_key in _plan_day_detail_cache_keys(plan_id=plan_id, day_number=day_number):
        data = await get_cache_data(hash_key=hashed_key)
        if data and isinstance(data, dict):
            return PlanDayDTO(**data)
    return None


async def set_plan_day_detail_cache(plan_id: UUID, day_number: int, data: PlanDayDTO) -> None:
    hashed_key = _plan_day_detail_cache_keys(plan_id=plan_id, day_number=day_number)[0]
    await set_cache(hash_key=hashed_key, value=data, cache_time_out=_plan_timeout())


async def invalidate_plan_day_detail_cache(plan_id: UUID, day_number: int) -> int:
    keys = _plan_day_detail_cache_keys(plan_id=plan_id, day_number=day_number)
    for hashed_key in keys:
        await delete_cache(hash_key=hashed_key)
    return len(keys)


async def invalidate_all_plan_day_detail_caches_for_plan(db: Session, plan_id: UUID) -> int:
    days = await run_in_threadpool(get_days_by_plan_id, db=db, plan_id=plan_id)
    keys_deleted = 0
    for day in days:
        keys_deleted += await invalidate_plan_day_detail_cache(
            plan_id=plan_id,
            day_number=day.day_number,
        )
    return keys_deleted


def _resolve_plan_day_for_task(db: Session, task_id: UUID) -> Optional[tuple[UUID, int]]:
    task = get_task_by_id(db=db, task_id=task_id)
    if not task:
        return None
    plan_item = get_plan_item_by_id(db=db, day_id=task.plan_item_id)
    if not plan_item:
        return None
    return plan_item.plan_id, plan_item.day_number


def _resolve_plan_day_for_day(db: Session, day_id: UUID) -> Optional[tuple[UUID, int]]:
    plan_item = get_plan_item_by_id(db=db, day_id=day_id)
    if not plan_item:
        return None
    return plan_item.plan_id, plan_item.day_number


async def invalidate_plan_day_cache_for_task(db: Session, task_id: UUID) -> None:
    resolved = _resolve_plan_day_for_task(db=db, task_id=task_id)
    if not resolved:
        return
    plan_id, day_number = resolved
    await invalidate_plan_day_detail_cache(plan_id=plan_id, day_number=day_number)


async def invalidate_plan_day_cache_for_day(db: Session, day_id: UUID) -> None:
    resolved = _resolve_plan_day_for_day(db=db, day_id=day_id)
    if not resolved:
        return
    plan_id, day_number = resolved
    await invalidate_plan_day_detail_cache(plan_id=plan_id, day_number=day_number)


def schedule_invalidate_plan_day_cache(plan_id: UUID, day_number: int) -> None:
    """Invalidate plan day cache from sync callers without blocking."""
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(invalidate_plan_day_detail_cache(plan_id=plan_id, day_number=day_number))
    except RuntimeError:
        asyncio.run(invalidate_plan_day_detail_cache(plan_id=plan_id, day_number=day_number))


def schedule_invalidate_plan_day_cache_for_task(db: Session, task_id: UUID) -> None:
    resolved = _resolve_plan_day_for_task(db=db, task_id=task_id)
    if not resolved:
        return
    plan_id, day_number = resolved
    schedule_invalidate_plan_day_cache(plan_id=plan_id, day_number=day_number)


def schedule_invalidate_plan_day_cache_for_day(db: Session, day_id: UUID) -> None:
    resolved = _resolve_plan_day_for_day(db=db, day_id=day_id)
    if not resolved:
        return
    plan_id, day_number = resolved
    schedule_invalidate_plan_day_cache(plan_id=plan_id, day_number=day_number)
