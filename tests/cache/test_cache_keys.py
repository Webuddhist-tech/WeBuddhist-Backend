from unittest.mock import patch
from uuid import uuid4

from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_keys import (
    SCHEMA_VERSION,
    build_cache_key,
    namespace_scan_pattern,
    user_scan_pattern,
    user_segment,
)


def test_key_starts_with_a_readable_namespace():
    """The namespace is what makes a key evictable as part of a group."""
    key = build_cache_key(CacheType.SERIES_LIST, ["en", 0, 10])
    assert key.startswith("series_list:")


def test_anonymous_and_user_keys_differ():
    parts = ["en", 0, 10]
    anon = build_cache_key(CacheType.SERIES_LIST, parts)
    user = build_cache_key(CacheType.SERIES_LIST, parts, user_identity="iss|alice")
    assert anon != user
    assert ":anon:" in anon


def test_two_users_never_share_a_key():
    parts = ["en", 0, 10]
    alice = build_cache_key(CacheType.EVENT_LIST, parts, user_identity="iss|alice")
    bob = build_cache_key(CacheType.EVENT_LIST, parts, user_identity="iss|bob")
    assert alice != bob


def test_each_part_changes_the_key():
    """A filter left out of the key would serve one caller's result to another."""
    base = build_cache_key(CacheType.PLAN_LIST, ["en", 0, 10])
    for variant in (["bo", 0, 10], ["en", 10, 10], ["en", 0, 20]):
        assert build_cache_key(CacheType.PLAN_LIST, variant) != base


def test_none_is_distinct_from_the_string_none():
    assert build_cache_key(CacheType.PLAN_LIST, [None]) != build_cache_key(
        CacheType.PLAN_LIST, ["None"]
    )


def test_schema_version_participates_in_the_key():
    before = build_cache_key(CacheType.PLAN_LIST, ["en"])
    with patch("pecha_api.cache.cache_keys.SCHEMA_VERSION", SCHEMA_VERSION + "x"):
        after = build_cache_key(CacheType.PLAN_LIST, ["en"])
    assert before != after


def test_user_segment_does_not_leak_the_identity():
    """Keys show up in logs and in redis-cli --scan."""
    identity = "https://issuer/|user@example.com"
    segment = user_segment(identity)
    assert "user@example.com" not in segment
    assert segment.startswith("u")


def test_user_pattern_matches_only_that_user():
    with patch("pecha_api.cache.cache_keys.config.get", return_value="pecha:"):
        pattern = user_scan_pattern(CacheType.EVENT_LIST, "iss|alice")
        key = build_cache_key(CacheType.EVENT_LIST, ["en"], user_identity="iss|alice")
        other = build_cache_key(CacheType.EVENT_LIST, ["en"], user_identity="iss|bob")
    prefix = pattern[: -len("*")]
    assert f"pecha:{key}".startswith(prefix)
    assert not f"pecha:{other}".startswith(prefix)


def test_namespace_pattern_matches_every_key_in_the_namespace():
    with patch("pecha_api.cache.cache_keys.config.get", return_value="pecha:"):
        pattern = namespace_scan_pattern(CacheType.EVENT_LIST)
        anon = build_cache_key(CacheType.EVENT_LIST, ["en"])
        user = build_cache_key(CacheType.EVENT_LIST, ["en"], user_identity="iss|alice")
    prefix = pattern[: -len("*")]
    assert f"pecha:{anon}".startswith(prefix)
    assert f"pecha:{user}".startswith(prefix)


def test_uuid_parts_are_usable():
    plan_id = uuid4()
    assert build_cache_key(CacheType.PLAN_DETAIL, [plan_id]) != build_cache_key(
        CacheType.PLAN_DETAIL, [uuid4()]
    )
