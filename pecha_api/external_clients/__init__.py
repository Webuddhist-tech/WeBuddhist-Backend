import asyncio
import logging
from functools import lru_cache
from typing import Any, Dict, Optional

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
_LIMITS = httpx.Limits(
    max_connections=20,
    max_keepalive_connections=10,
    keepalive_expiry=15.0,
)

# A disconnect before any response bytes arrive means the request was never
# processed, so replaying these idempotent reads is safe.
_RETRYABLE_ERRORS = (
    httpx.RemoteProtocolError,
    httpx.ConnectError,
    httpx.ConnectTimeout,
    httpx.ReadError,
)


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

    Only connection faults are retried; a response that arrives with an error
    status is returned untouched for the caller to raise on.
    """
    kwargs: Dict[str, Any] = {} if params is None else {"params": params}
    for attempt in range(attempts):
        try:
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
        httpx_args={"limits": _LIMITS},
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
        httpx_args={"limits": _LIMITS},
    )
