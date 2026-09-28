from pecha_api.cache.cache_enums import CacheType
from pecha_api.utils import Utils
from pecha_api import config
from pecha_api.recitations.recitations_response_models import RecitationDetailsResponse, RecitationDetailsRequest, RecitationsResponse
from pecha_api.cache.cache_repository import cache_type_enabled, set_cache, get_cache_data

# `set_cache` and `get_cache_data` honour the master switch and the breaker,
# but not CACHE_DISABLED_TYPES - they take a hash key, not a namespace, so they
# cannot tell which one they are serving. The per-type switch is checked here,
# where the namespace is known, or setting CACHE_DISABLED_TYPES=recitation_details
# would leave these endpoints reading and writing Redis exactly as before.


async def set_recitation_by_text_id_cache(text_id: str, recitation_details_request: RecitationDetailsRequest, cache_type: CacheType, data: RecitationDetailsResponse) -> None:

    if not cache_type_enabled(cache_type):
        return
    payload = [text_id, recitation_details_request, cache_type]
    hashed_key: str = Utils.generate_hash_key(payload = payload)
    cache_time_out = config.get_int("CACHE_TEXT_TIMEOUT")
    await set_cache(hash_key=hashed_key, value=data, cache_time_out=cache_time_out)

async def get_recitation_by_text_id_cache(text_id: str = None, recitation_details_request: RecitationDetailsRequest = None, cache_type: CacheType = None) -> RecitationDetailsResponse:

    if not cache_type_enabled(cache_type):
        return None
    payload = [text_id, recitation_details_request, cache_type]
    hashed_key: str = Utils.generate_hash_key(payload = payload)
    cache_data: RecitationDetailsResponse = await get_cache_data(hash_key = hashed_key)
    if cache_data and isinstance(cache_data, dict):
        cache_data = RecitationDetailsResponse(**cache_data)
    return cache_data

async def set_recitation_list_cache(language: str, search: str, skip: int, limit: int, cache_type: CacheType, data: RecitationsResponse) -> None:

    if not cache_type_enabled(cache_type):
        return
    payload = [language, search, skip, limit, cache_type]
    hashed_key: str = Utils.generate_hash_key(payload = payload)
    cache_time_out = config.get_int("CACHE_TEXT_TIMEOUT")
    await set_cache(hash_key=hashed_key, value=data, cache_time_out=cache_time_out)

async def get_recitation_list_cache(language: str = None, search: str = None, skip: int = None, limit: int = None, cache_type: CacheType = None) -> RecitationsResponse:

    if not cache_type_enabled(cache_type):
        return None
    payload = [language, search, skip, limit, cache_type]
    hashed_key: str = Utils.generate_hash_key(payload = payload)
    cache_data: RecitationsResponse = await get_cache_data(hash_key = hashed_key)
    if cache_data and isinstance(cache_data, dict):
        cache_data = RecitationsResponse(**cache_data)
    return cache_data