import asyncio
import logging
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any, Dict, Optional
from weakref import WeakKeyDictionary

import httpx

from pecha_api import config
from pecha_api.external_clients.open_pecha_client.open_pecha_client.client import (
    AuthenticatedClient,
    Client,
)

logger = logging.getLogger(__name__)

# The upstream proxy closes idle keep-alive connections on its own timer. Expiring
# pooled connections sooner than it does keeps us from writing a request onto a
# socket the server has already closed.
_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _limits() -> httpx.Limits:
    return httpx.Limits(
        max_connections=config.get_int("OPENPECHA_MAX_CONNECTIONS"),
        max_keepalive_connections=10,
        keepalive_expiry=15.0,
    )

# Every one of these leaves the caller with no response at all. The reads
# behind them are idempotent GETs, so replaying is safe even for the timeouts,
# where the request may well have reached the server.
_RETRYABLE_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
    httpx.ReadTimeout,
    httpx.PoolTimeout,
)

class OpenPechaQueueTimeout(Exception):
    """Gave up waiting for a slot on the openpecha concurrency gate.

    Deliberately not in `_RETRYABLE_ERRORS`: the request never went out, and
    retrying it means re-joining the same queue that just proved too long.
    """


# Gate every openpecha call, not just one caller's: plan resolution, bookmarks
# and search all fan out over segments independently, so a per-caller cap still
# lets them collectively exhaust the pool and fail on PoolTimeout. Held below
# max_connections so the pool itself never becomes the bottleneck.
#
# Built on first use rather than at import so its size comes from config, and
# kept afterwards: resizing it while requests hold permits would hand out more
# than the new size allows.
#
# Held per event loop. An asyncio.Semaphore binds to the loop the first time a
# caller actually waits on it and refuses every other loop from then on, so a
# single shared instance is only correct while exactly one loop ever exists -
# true of the server, not of anything that calls asyncio.run more than once.
# The map is weak so a finished loop takes its gate with it.
_semaphores: "WeakKeyDictionary[asyncio.AbstractEventLoop, asyncio.Semaphore]" = (
    WeakKeyDictionary()
)


def _get_semaphore() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    semaphore = _semaphores.get(loop)
    if semaphore is None:
        semaphore = asyncio.Semaphore(config.get_int("OPENPECHA_MAX_CONCURRENCY"))
        _semaphores[loop] = semaphore
    return semaphore


def _resolve_pecha_base_url() -> str:
    """Return EXTERNAL_DEV_PECHA_API_URL when set, otherwise fall back to EXTERNAL_PECHA_API_URL."""
    dev_url = config.get("EXTERNAL_DEV_PECHA_API_URL")
    if dev_url:
        return dev_url
    return config.get("EXTERNAL_PECHA_API_URL")


async def get_with_retry(
    http_client: httpx.AsyncClient,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    attempts: int = 3,
) -> httpx.Response:
    """GET `url`, retrying transport-level failures with exponential backoff.

    Only transport faults are retried; a response that arrives with an error
    status is returned untouched for the caller to raise on. Concurrency across
    all openpecha callers is capped while the request is in flight, and released
    over the backoff so a retrying request does not hold a slot it is not using.
    """
    kwargs: Dict[str, Any] = {} if params is None else {"params": params}
    for attempt in range(attempts):
        try:
            async with _gate():
                return await http_client.get(url, **kwargs)
        except _RETRYABLE_ERRORS as error:
            if attempt == attempts - 1:
                raise
            logger.warning(
                "openpecha GET %s failed (%s), retrying %d/%d",
                url,
                type(error).__name__,
                attempt + 1,
                attempts - 1,
            )
            await asyncio.sleep(0.1 * 2 ** attempt)


@asynccontextmanager
async def _gate():
    """Hold a slot on the concurrency gate, or give up waiting for one.

    Acquiring is what a caller actually queues on: the per-request timeouts
    below only start once a slot is in hand, so without a bound here a wide
    fan-out against a slow openpecha waits for as long as it takes and the
    request has no timeout at all.
    """
    semaphore = _get_semaphore()
    timeout = config.get_float("OPENPECHA_QUEUE_TIMEOUT")
    try:
        await asyncio.wait_for(semaphore.acquire(), timeout=timeout)
    except asyncio.TimeoutError as error:
        raise OpenPechaQueueTimeout(
            f"No openpecha slot within {timeout}s"
        ) from error
    try:
        yield
    finally:
        semaphore.release()


@lru_cache()
def get_open_pecha_client() -> Client:
    """Get a configured OpenPecha API client instance.
    
    Returns a cached client instance for reuse across requests.
    Configure via config:
        - EXTERNAL_DEV_PECHA_API_URL: Base URL for the API (falls back to EXTERNAL_PECHA_API_URL)
    """
    return Client(
        base_url=_resolve_pecha_base_url(),
        raise_on_unexpected_status=True,
        follow_redirects=True,
        timeout=_TIMEOUT,
        httpx_args={"limits": _limits()},
    )


@lru_cache()
def get_authenticated_open_pecha_client() -> AuthenticatedClient:
    """Get a configured authenticated OpenPecha API client instance.
    
    Returns a cached client instance with API key authentication.
    Configure via config:
        - EXTERNAL_DEV_PECHA_API_URL: Base URL for the API (falls back to EXTERNAL_PECHA_API_URL)
        - EXTERNAL_OPENPECHA_API_KEY: API key for authentication (required)
        - EXTERNAL_PECHA_APP_NAME: Application name header (default: webuddhist)
    
    Raises:
        ValueError: If EXTERNAL_OPENPECHA_API_KEY is not set
    """
    api_key = config.get("EXTERNAL_OPENPECHA_API_KEY")
    if not api_key:
        raise ValueError("EXTERNAL_OPENPECHA_API_KEY is required in config")
    
    app_name = config.get("EXTERNAL_PECHA_APP_NAME")
    
    return AuthenticatedClient(
        base_url=_resolve_pecha_base_url(),
        token=api_key,
        prefix="",
        auth_header_name="X-API-Key",
        raise_on_unexpected_status=True,
        headers={"X-Application": app_name},
        follow_redirects=True,
        timeout=_TIMEOUT,
        httpx_args={"limits": _limits()},
    )
