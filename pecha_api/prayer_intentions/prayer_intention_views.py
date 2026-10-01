from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Query
from starlette.concurrency import run_in_threadpool

from .prayer_intention_service import get_all_prayer_intentions_service
from .prayer_intention_response_models import PrayerIntentionsResponse

prayer_intention_router = APIRouter(prefix="/intentions", tags=["Prayer intentions"])


@prayer_intention_router.get("", response_model=PrayerIntentionsResponse)
async def get_prayer_intentions(
    event: Annotated[
        Optional[UUID],
        Query(description="When set, return intentions allowed for this event"),
    ] = None,
) -> PrayerIntentionsResponse:
    return await run_in_threadpool(get_all_prayer_intentions_service, event)
