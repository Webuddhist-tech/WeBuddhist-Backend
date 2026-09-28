import uuid

from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_keys import build_cache_key, resource_scan_pattern


def test_event_detail_cache_key_includes_resource_id():
    event_id = uuid.uuid4()
    key = build_cache_key(
        cache_type=CacheType.EVENT_DETAIL,
        parts=[event_id, "en"],
        user_identity=None,
        resource_id=event_id,
    )
    assert key.startswith(f"event_detail:r:{event_id}:")


def test_resource_scan_pattern_scopes_to_one_event():
    event_id = uuid.uuid4()
    pattern = resource_scan_pattern(CacheType.EVENT_DETAIL, event_id)
    assert f"event_detail:r:{event_id}:" in pattern
