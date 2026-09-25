"""The CACHE_ENABLED / CACHE_DISABLED_TYPES switches.

Switched off, the cache must be entirely absent from the request path: the
loader runs, Redis is never contacted, and a write sweeps nothing.
"""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import BaseModel

from pecha_api import config
from pecha_api.cache import cached_response as cached_response_module
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_repository import (
    cache_enabled,
    cache_is_available,
    cache_type_enabled,
    disabled_cache_types,
)
from pecha_api.cache.cached_response import cached_response, invalidate_namespaces


class Sample(BaseModel):
    value: str


@pytest.fixture
def clean_pending():
    cached_response_module._pending_invalidations.clear()
    yield
    cached_response_module._pending_invalidations.clear()


def _env(**values):
    """Patch config.get for the keys given, deferring to the real one otherwise."""
    real_get = config.get

    def fake_get(key):
        return values.get(key, real_get(key))

    return patch("pecha_api.config.get", side_effect=fake_get)


class TestGetBool:
    @pytest.mark.parametrize("raw", ["true", "TRUE", " True ", "1", "yes", "on"])
    def test_truthy_spellings(self, raw):
        with _env(CACHE_ENABLED=raw):
            assert config.get_bool("CACHE_ENABLED") is True

    @pytest.mark.parametrize("raw", ["false", "FALSE", " off ", "0", "no", ""])
    def test_falsy_spellings(self, raw):
        with _env(CACHE_ENABLED=raw):
            assert config.get_bool("CACHE_ENABLED") is False

    def test_an_unrecognised_value_raises(self):
        with _env(CACHE_ENABLED="maybe"):
            with pytest.raises(ValueError):
                config.get_bool("CACHE_ENABLED")

    def test_the_cache_stays_on_when_the_flag_is_garbage(self):
        """A typo in the kill switch must not take the cache down with it."""
        with _env(CACHE_ENABLED="maybe"):
            assert cache_enabled() is True


class TestMasterSwitch:
    def test_defaults_to_on(self):
        assert cache_enabled() is True
        assert cache_is_available() is True

    def test_off_makes_the_cache_unavailable(self):
        with _env(CACHE_ENABLED="false"):
            assert cache_enabled() is False
            assert cache_is_available() is False
            assert cache_type_enabled(CacheType.PLAN_DETAIL) is False

    @pytest.mark.asyncio
    async def test_off_runs_the_loader_and_never_touches_redis(self):
        calls = []

        def load():
            calls.append(1)
            return Sample(value="fresh")

        with _env(CACHE_ENABLED="false"), \
             patch("pecha_api.cache.cached_response.get_cache_data", new_callable=AsyncMock) as mock_get, \
             patch("pecha_api.cache.cached_response.set_cache", new_callable=AsyncMock) as mock_set:
            result = await cached_response(
                cache_type=CacheType.PLAN_DETAIL, parts=["a"], model=Sample,
                loader=load, timeout=60,
            )

        assert result == Sample(value="fresh")
        assert calls == [1]
        mock_get.assert_not_awaited()
        mock_set.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_off_runs_an_async_loader_too(self):
        async def load():
            return Sample(value="async-fresh")

        with _env(CACHE_ENABLED="false"), \
             patch("pecha_api.cache.cached_response.get_cache_data", new_callable=AsyncMock), \
             patch("pecha_api.cache.cached_response.set_cache", new_callable=AsyncMock):
            result = await cached_response(
                cache_type=CacheType.PLAN_DETAIL, parts=["a"], model=Sample,
                loader=load, timeout=60,
            )

        assert result == Sample(value="async-fresh")

    @pytest.mark.asyncio
    async def test_off_sweeps_nothing_on_a_write(self, clean_pending):
        with _env(CACHE_ENABLED="false"), \
             patch("pecha_api.cache.cached_response.delete_by_pattern",
                   new_callable=AsyncMock) as mock_delete:
            removed = await invalidate_namespaces([CacheType.PLAN_DETAIL, CacheType.PLAN_LIST])

        assert removed == 0
        mock_delete.assert_not_awaited()
        # A namespace nothing was written to owes no eviction.
        assert cached_response_module._pending_invalidations == {}


class TestPerTypeSwitch:
    def test_parses_the_list(self):
        with _env(CACHE_DISABLED_TYPES="plan_detail, PLAN_LIST ,"):
            assert disabled_cache_types() == frozenset(
                {CacheType.PLAN_DETAIL, CacheType.PLAN_LIST}
            )

    def test_empty_by_default(self):
        assert disabled_cache_types() == frozenset()

    def test_unknown_names_are_ignored(self):
        with _env(CACHE_DISABLED_TYPES="plan_detail,not_a_namespace"):
            assert disabled_cache_types() == frozenset({CacheType.PLAN_DETAIL})

    def test_only_the_listed_namespace_is_off(self):
        with _env(CACHE_DISABLED_TYPES="plan_detail"):
            assert cache_type_enabled(CacheType.PLAN_DETAIL) is False
            assert cache_type_enabled(CacheType.PLAN_LIST) is True
            # The master switch is untouched, so Redis stays in play.
            assert cache_is_available() is True

    @pytest.mark.asyncio
    async def test_a_listed_namespace_bypasses_while_others_cache(self):
        with _env(CACHE_DISABLED_TYPES="plan_detail"), \
             patch("pecha_api.cache.cached_response.get_cache_data", new_callable=AsyncMock,
                   return_value={"value": "cached"}), \
             patch("pecha_api.cache.cached_response.set_cache", new_callable=AsyncMock):
            bypassed = await cached_response(
                cache_type=CacheType.PLAN_DETAIL, parts=["a"], model=Sample,
                loader=lambda: Sample(value="fresh"), timeout=60,
            )
            served = await cached_response(
                cache_type=CacheType.PLAN_LIST, parts=["a"], model=Sample,
                loader=lambda: Sample(value="fresh"), timeout=60,
            )

        assert bypassed.value == "fresh"
        assert served.value == "cached"
