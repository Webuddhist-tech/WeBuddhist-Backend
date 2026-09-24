"""Router-level cache invalidation for write endpoints.

Attaching invalidation to each write by hand means every new endpoint has to
remember it, and the one that forgets serves stale content for a full timeout
with nothing to show what went wrong. A dependency on the router covers every
route it carries, including the ones not written yet.

The teardown of a `yield` dependency runs after the response is produced, so
the caller does not wait on Redis, and a failure here cannot turn a write that
succeeded into an error the client sees.
"""

import logging
from typing import Callable, Optional

from starlette.requests import Request
from starlette.websockets import WebSocket

from pecha_api.cache.cache_enums import CacheType
from pecha_api.cache.cache_identity import cache_identity_from_token
from pecha_api.cache.cached_response import invalidate_namespaces, invalidate_user_namespaces

logger = logging.getLogger(__name__)

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def invalidate_on_write(*cache_types: CacheType) -> Callable:
    """Dependency that clears `cache_types` after any write on this router.

    It fires on a rejected write too - a 403 sweeps the same namespaces a 200
    would. Rebuilding a cache nobody asked to rebuild costs one query per key
    on the next read, which is a better trade than reasoning about which
    failures left the database untouched.
    """

    async def _invalidate(request: Request = None, websocket: WebSocket = None):
        yield
        # A WebSocket route on this router gets `websocket` and no `request`;
        # a socket is not a write, so there is nothing to invalidate.
        if request is None or request.method not in WRITE_METHODS:
            return
        try:
            await invalidate_namespaces(cache_types)
        except Exception as cache_error:
            # invalidate_namespaces already swallows per-namespace failures;
            # this is the belt to that braces. A write is not undone by a
            # cache that could not be reached.
            logger.error("Post-write cache invalidation failed: %s", cache_error)

    return _invalidate


def _bearer_token(request: Optional[Request]) -> str:
    if request is None:
        return ""
    header = request.headers.get("Authorization") or ""
    scheme, _, credentials = header.partition(" ")
    return credentials.strip() if scheme.lower() == "bearer" else ""


def invalidate_caller_on_write(*cache_types: CacheType) -> Callable:
    """Clear only the caller's entries in `cache_types` after a write.

    For routers whose writes change what the writer sees and little else:
    joining an event, liking a post. Sweeping the whole namespace on each of
    those would mean 2000 people joining a puja evict the cache 2000 times,
    and nobody is ever served from it. What such a write changes for other
    people - a count, a total - rides on the namespace's short timeout.
    """

    async def _invalidate(request: Request = None, websocket: WebSocket = None):
        yield
        if request is None or request.method not in WRITE_METHODS:
            return
        try:
            await invalidate_user_namespaces(cache_types, cache_identity_from_token(_bearer_token(request)))
        except Exception as cache_error:
            logger.error("Post-write cache invalidation failed: %s", cache_error)

    return _invalidate
