import fnmatch
import uuid
from unittest.mock import patch

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_keys import (
    build_cache_key,
    resource_scan_pattern,
    user_scan_pattern,
    user_segment,
)


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


def test_event_detail_user_scan_pattern_matches_resource_scoped_keys():
    event_id = uuid.uuid4()
    identity = "iss|alice"
    hash_key = build_cache_key(
        cache_type=CacheType.EVENT_DETAIL,
        parts=[event_id, "en"],
        user_identity=identity,
        resource_id=event_id,
    )
    prefix = "pecha:"
    with patch.object(config, "get", return_value=prefix):
        pattern = user_scan_pattern(CacheType.EVENT_DETAIL, identity)
        full_key = f"{prefix}{hash_key}"
        assert fnmatch.fnmatch(full_key, pattern)


def test_event_list_user_scan_pattern_unchanged():
    prefix = "pecha:"
    identity = "iss|bob"
    with patch.object(config, "get", return_value=prefix):
        pattern = user_scan_pattern(CacheType.EVENT_LIST, identity)
    assert pattern == f"{prefix}event_list:{user_segment(identity)}:*"
