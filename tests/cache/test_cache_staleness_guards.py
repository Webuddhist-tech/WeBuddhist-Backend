"""Cases where a cache hit must not be trusted on its own."""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import TimeoutError as SQLAlchemyPoolTimeout

from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_keys import build_cache_key


@pytest.mark.asyncio
async def test_group_access_is_rechecked_on_a_cache_hit():
    """Membership is revocable: someone removed from a private group must stop
    seeing its posts, not keep their own cached copy until it expires."""
    from pecha_api.group_posts import posts_cache_service

    group_id = uuid4()
    with patch.object(posts_cache_service, "cached_response", new_callable=AsyncMock) as mock_cached, \
         patch.object(posts_cache_service, "_assert_group_access",
                      side_effect=HTTPException(status_code=404, detail="Not found")), \
         patch.object(posts_cache_service, "cache_identity_from_token",
                      new_callable=AsyncMock, return_value=None):
        with pytest.raises(HTTPException) as exc:
            await posts_cache_service.list_group_posts_cached(group_id=group_id, token="t")

    assert exc.value.status_code == 404
    mock_cached.assert_not_awaited(), "access must be refused before the cache is consulted"


@pytest.mark.asyncio
async def test_post_detail_rechecks_access_after_a_hit():
    from pecha_api.group_posts import posts_cache_service

    post = MagicMock(group_id=uuid4())
    with patch.object(posts_cache_service, "cached_response", new_callable=AsyncMock,
                      return_value=post), \
         patch.object(posts_cache_service, "_assert_group_access",
                      side_effect=HTTPException(status_code=404, detail="Not found")) as mock_check, \
         patch.object(posts_cache_service, "cache_identity_from_token",
                      new_callable=AsyncMock, return_value=None):
        with pytest.raises(HTTPException):
            await posts_cache_service.get_group_post_detail_cached(post_id=uuid4(), token="t")

    mock_check.assert_called_once()
    assert mock_check.call_args.args[0] == post.group_id


@pytest.mark.asyncio
async def test_public_feed_key_changes_when_group_membership_changes():
    """The cross-group feed spans private groups you have joined, so the key
    carries the scope and a removal makes the old entry unreachable."""
    from pecha_api.group_posts import posts_cache_service

    seen = []

    async def fake_cached(**kwargs):
        seen.append(kwargs["parts"])
        return MagicMock()

    scopes = iter(["scope-with-group", "scope-without-group"])
    with patch.object(posts_cache_service, "cached_response", side_effect=fake_cached), \
         patch.object(posts_cache_service, "_group_scope_fingerprint",
                      side_effect=lambda *a: next(scopes)), \
         patch.object(posts_cache_service, "cache_identity_from_token",
                      new_callable=AsyncMock, return_value="iss|alice"):
        await posts_cache_service.list_public_group_posts_cached(token="t")
        await posts_cache_service.list_public_group_posts_cached(token="t")

    assert seen[0] != seen[1]


def test_anonymous_public_feed_key_tracks_the_public_group_set():
    """Making a public group private must change the anonymous feed key.
    A constant scope would keep serving the group's posts until expiry."""
    from pecha_api.group_posts import posts_cache_service

    first, second = uuid4(), uuid4()
    scopes = iter([[first, second], [first]])

    def _public_ids(db):
        return next(scopes)

    with patch.object(posts_cache_service, "SessionLocal"), \
         patch.object(posts_cache_service, "_resolve_user_id", return_value=None), \
         patch.object(posts_cache_service, "get_public_group_ids", side_effect=_public_ids):
        before = posts_cache_service._group_scope_fingerprint(None, False)
        after = posts_cache_service._group_scope_fingerprint(None, False)

    assert before != after


def test_event_list_key_tracks_group_access():
    """Removal from a private group changes the listing key, so the old
    entry — still holding that group's events — is never read again."""
    from pecha_api.events import events_cache_service

    user_id = uuid4()
    kept, removed = uuid4(), uuid4()
    scopes = iter([[kept, removed], [kept]])

    def _listing(**kwargs):
        return next(scopes), set()

    with patch.object(events_cache_service, "SessionLocal"), \
         patch.object(events_cache_service, "validate_and_extract_user_details",
                      return_value=MagicMock(id=user_id)), \
         patch.object(events_cache_service, "resolve_event_listing_group_ids",
                      side_effect=_listing):
        before = events_cache_service._event_access_fingerprint("token", False, None)
        after = events_cache_service._event_access_fingerprint("token", False, None)

    assert before != after
    assert events_cache_service._event_access_fingerprint(None, False, None) is None


def test_plan_daily_key_rolls_over_at_midnight():
    """An entry built before midnight for an unspecified date must not serve
    yesterday's reading afterwards."""
    from pecha_api.plans.public import plans_read_cache

    plan_id = uuid4()
    today = date(2026, 9, 24)

    def key_for(day):
        with patch.object(plans_read_cache, "_utc_today", return_value=day):
            return build_cache_key(
                CacheType.PLAN_DAILY, [plan_id, None, plans_read_cache._utc_today(), None]
            )

    assert key_for(today) != key_for(today + timedelta(days=1))


def test_an_explicit_date_still_keys_on_that_date():
    from pecha_api.plans.public import plans_read_cache

    plan_id = uuid4()
    with patch.object(plans_read_cache, "_utc_today", return_value=date(2026, 9, 24)):
        explicit = build_cache_key(
            CacheType.PLAN_DAILY, [plan_id, date(2026, 1, 1), plans_read_cache._utc_today(), None]
        )
        other = build_cache_key(
            CacheType.PLAN_DAILY, [plan_id, date(2026, 1, 2), plans_read_cache._utc_today(), None]
        )
    assert explicit != other


def test_pool_timeout_survives_the_published_plan_handlers():
    """A short pool timeout is only useful if it reaches the 503 handler
    instead of being folded into a generic 500."""
    from pecha_api.plans.public import plan_service

    with patch.object(plan_service, "SessionLocal",
                      side_effect=SQLAlchemyPoolTimeout("pool exhausted")):
        for call in (
            lambda: plan_service._get_published_plans_sync(),
            lambda: plan_service._get_published_plan_sync(plan_id=uuid4(), timezone_name=None),
        ):
            with pytest.raises(SQLAlchemyPoolTimeout):
                call()
