import logging
from typing import Optional, Dict, Any

from pecha_api.external_clients import get_authenticated_open_pecha_client, get_with_retry

logger = logging.getLogger(__name__)


async def fetch_category_by_id(category_id: str, language: Optional[str] = None) -> Optional[Dict[str, Any]]:
    client = get_authenticated_open_pecha_client()
    http_client = client.get_async_httpx_client()
    params: Dict[str, Any] = {
        "language": language.strip().lower() if language else language,
    }
    response = await get_with_retry(http_client, f"/v2/categories/{category_id}", params=params)
    response.raise_for_status()
    return response.json()
