from fastapi import APIRouter

from .ambient_sound_service import get_all_ambient_sounds_service
from .ambient_sound_response_models import AmbientSoundsResponse

ambient_sound_router = APIRouter(prefix="/ambient-sounds", tags=["Ambient Sounds"])


@ambient_sound_router.get("", response_model=AmbientSoundsResponse)
async def get_all_ambient_sounds():
    return get_all_ambient_sounds_service()
