import json
import time
from typing import Any, Optional, List

from redis.asyncio import Redis

from pecha_api import config
from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.presigned_expiry import seconds_until_first_expiry
import logging
from pydantic.json import pydantic_encoder


_client: Optional[Redis] = None

# Circuit breaker. Timeouts bound a single call; this bounds how often we pay
# one. Without it, a Redis that is down costs every request its full connect
# timeout, and the cache becomes a tax on exactly the traffic it exists to
# absorb. After a failure the cache is treated as absent for a short window
# and requests go straight to the database.
_circuit_open_until: float = 0.0


def _circuit_is_open() -> bool:
    return time.monotonic() < _circuit_open_until


def _trip_circuit() -> None:
    global _circuit_open_until
    _circuit_open_until = time.monotonic() + config.get_float("CACHE_CIRCUIT_BREAK_SECONDS")


def note_cache_failure() -> None:
    """Open the breaker from code that talks to Redis outside this module."""
    _trip_circuit()


def cache_is_available() -> bool:
    """False while the breaker is open; callers skip the cache entirely."""
    return not _circuit_is_open()


def reset_circuit() -> None:
    """Close the breaker immediately (used by an explicit admin action)."""
    global _circuit_open_until
    _circuit_open_until = 0.0


def get_client() -> Redis:
    """Get or create Redis client instance.

    The timeouts are the point. Without them a Redis that is up but not
    answering blocks every cache call for as long as it takes to notice, on
    the event loop, for every request at once - a cache is supposed to shed
    load, not become the thing that holds it. Bounded, a sick Redis costs each
    request one short wait and then it falls through to the database.
    """
    global _client
    if _client is None:
        redis_url = config.get("CACHE_CONNECTION_STRING")
        _client = Redis.from_url(
            redis_url,
            socket_connect_timeout=config.get_float("CACHE_CONNECT_TIMEOUT"),
            socket_timeout=config.get_float("CACHE_SOCKET_TIMEOUT"),
            retry_on_timeout=False,
            decode_responses=True,
        )
    return _client


def _build_key(key: str) -> str:
    """Build cache key with prefix"""
    prefix = config.get("CACHE_PREFIX")
    return f"{prefix}{key}"



def _timeout_for(value: str, requested: int) -> int:
    """Shorten a timeout that would outlive the payload's presigned URLs.

    Every caller picks its timeout from how fast its content changes, which
    is the right question but not the only one: a body carrying signed image
    URLs also stops being servable when those signatures lapse. Held to the
    shorter of the two, an entry is dropped while its links still work
    instead of spending its last hours handing out dead ones.

    The margin is what the response still has left when it is served at the
    very end of the window - a page opened then has that long to load its
    images.
    """
    remaining = seconds_until_first_expiry(value)
    if remaining is None:
        return requested

    usable = remaining - config.get_int("PRESIGNED_URL_SAFETY_MARGIN")
    if usable <= 0:
        # Signed so close to its deadline that no cached copy of it is worth
        # keeping. Rare enough to be worth hearing about: it means the signer
        # is handing out URLs shorter-lived than the margin.
        logging.warning(
            "Not caching a response whose presigned URLs expire in %ds", remaining
        )
        return 0
    return min(requested, usable)


async def set_cache(hash_key: str, value: Any, cache_time_out: int) -> bool:
    #Set value in cache with type-specific timeout
    if _circuit_is_open():
        return False
    try:
        client = get_client()
        full_key = _build_key(hash_key)
        if not isinstance(value, (str, bytes)):
            value = json.dumps(value, default=pydantic_encoder)
        if isinstance(value, bytes):
            cache_time_out = _timeout_for(value.decode("utf-8", "ignore"), cache_time_out)
        else:
            cache_time_out = _timeout_for(value, cache_time_out)
        if cache_time_out <= 0:
            return False
        return bool(await client.setex(full_key, cache_time_out, value))
    except Exception:
        _trip_circuit()
        logging.error("An error occurred in set_cache", exc_info=True)
        return False


async def get_cache_data(hash_key: str) -> Optional[Any]:
    """Get value from cache"""
    if _circuit_is_open():
        return None
    try:
        client = get_client()
        full_key = _build_key(hash_key)
        value = await client.get(full_key)
        if value is None:
            return None
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            logging.error("Failed to decode JSON from cache", exc_info=True)
            return value
    except Exception:
        _trip_circuit()
        logging.error("An error occurred in get_cache_data", exc_info=True)
        return None


async def delete_cache(hash_key: str) -> bool:
    """Delete key from cache"""
    if _circuit_is_open():
        return False
    try:
        client = get_client()
        full_key = _build_key(hash_key)
        return bool(await client.delete(full_key))
    except Exception:
        _trip_circuit()
        logging.error("An error occurred in delete_cache", exc_info=True)
        return False


async def exists_in_cache(hash_key: str) -> bool:
    """Check if key exists in cache"""
    try:
        client = get_client()
        full_key = _build_key(hash_key)
        return bool(await client.exists(full_key))
    except Exception:
        logging.error("An error occurred in exists_in_cache", exc_info=True)
        return False

async def clear_cache(hash_key: str = None):
    try:
        client = get_client()
        full_key = _build_key(hash_key)
        return bool(await client.delete(full_key))
    except Exception:
        logging.error("An error occurred in clear_cache", exc_info=True)
        return False


async def update_cache(hash_key: str, value: Any, cache_time_out: int) -> bool:
    """Update existing cache entry with new value, resetting TTL to type-specific timeout"""
    try:
        client = get_client()
        full_key = _build_key(hash_key)
        
        # Check if key exists
        if not await client.exists(full_key):
            logging.warning(f"Cache key {hash_key} does not exist, cannot update")
            return False
        
        # Serialize value
        if not isinstance(value, (str, bytes)):
            value = json.dumps(value, default=pydantic_encoder)

        return bool(await client.setex(full_key, cache_time_out, value))
    except Exception:
        logging.error("An error occurred in update_cache", exc_info=True)
        return False


async def _delete_cache_keys(keys_to_delete: List[str], operation_type: str) -> bool:
    """Delete a list of full keys and log the operation."""
    try:
        client = get_client()
        if keys_to_delete:
            deleted_count = await client.delete(*keys_to_delete)
            logging.info(f"Invalidated {deleted_count} cache entries for {operation_type}")
            return deleted_count > 0
        logging.info(f"No cache entries found for {operation_type}")
        return True
    except Exception:
        logging.error(f"An error occurred while invalidating cache for {operation_type}", exc_info=True)
        return False


async def invalidate_cache_entries(text_id: Optional[str] = None, hash_keys: Optional[List[str]] = None) -> bool:
    try:
        # Validate input parameters
        if text_id and hash_keys:
            raise ValueError("Cannot specify both text_id and hash_keys. Use one or the other.")
        if not text_id and not hash_keys:
            raise ValueError("Must specify either text_id or hash_keys.")
        
        if text_id:
            return await invalidate_text_related_cache(text_id)
        return await invalidate_multiple_cache_keys(hash_keys or [])
    except Exception:
        error_context = f"text_id: {text_id}" if text_id else "multiple cache keys"
        logging.error(f"An error occurred while invalidating cache for {error_context}", exc_info=True)
        return False


async def invalidate_text_related_cache(text_id: str) -> bool:
    """Invalidate all cache entries related to a specific text_id"""
    try:
        client = get_client()
        prefix = config.get("CACHE_PREFIX")
        pattern = f"{prefix}{text_id}"
        keys_to_delete = await client.keys(pattern)
        operation_type = f"text_id: {text_id}"
        return await _delete_cache_keys(keys_to_delete, operation_type)
    except Exception:
        logging.error(f"An error occurred while invalidating cache for text_id: {text_id}", exc_info=True)
        return False


async def invalidate_multiple_cache_keys(hash_keys: List[str]) -> bool:
    """Invalidate multiple cache entries by their hash keys"""
    try:
        if not hash_keys:
            return True
        client = get_client()
        
        # Build full keys
        full_keys = [_build_key(key) for key in hash_keys]
        
        # Filter out non-existent keys
        keys_to_delete: List[str] = []
        for key in full_keys:
            if await client.exists(key):
                keys_to_delete.append(key)
        
        operation_type = f"{len(hash_keys)} hash keys"
        return await _delete_cache_keys(keys_to_delete, operation_type)
    except Exception:
        logging.error("An error occurred while invalidating multiple cache keys", exc_info=True)
        return False