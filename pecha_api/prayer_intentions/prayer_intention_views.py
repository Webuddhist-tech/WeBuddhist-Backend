from fastapi import APIRouter

from .prayer_intention_service import get_all_prayer_intentions_service
from .prayer_intention_response_models import PrayerIntentionsResponse

prayer_intention_router = APIRouter(prefix="/intentions", tags=["Prayer intentions"])


@prayer_intention_router.get("", response_model=PrayerIntentionsResponse)
async def get_prayer_intentions():
    return get_all_prayer_intentions_service()
