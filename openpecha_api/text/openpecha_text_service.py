import logging
from typing import Optional, Dict, Any

from pecha_api.external_clients import get_open_pecha_client, get_with_retry

logger = logging.getLogger(__name__)


async def fetch_texts_by_category(
    category_id: Optional[str] = None,
    language: Optional[str] = None,
    title: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "limit": limit,
        "offset": offset,
    }
    if category_id:
        params["category_id"] = category_id
    if language:
        params["language"] = language.strip().lower()
    if title:
        params["title"] = title

    client = get_open_pecha_client()
    http_client = client.get_async_httpx_client()
    response = await get_with_retry(http_client, "/v2/texts", params=params)
    response.raise_for_status()
    return response.json()


async def fetch_text_by_id(text_id: str) -> Optional[Dict[str, Any]]:
    client = get_open_pecha_client()
    http_client = client.get_async_httpx_client()
    response = await get_with_retry(http_client, f"/v2/texts/{text_id}")
    response.raise_for_status()
    return response.json()


async def search_by_content(
    query: str,
    search_type: Optional[str] = None,
    limit: Optional[int] = 10,
    text_id: Optional[str] = None,
    edition_id: Optional[str] = None,
) -> Dict[str, Any]:
    
    params: Dict[str, Any] = {
        "query": query,
        "limit": limit,
    }
    if search_type:
        params["search_type"] = search_type
    if text_id:
        params["text_id"] = text_id
    if edition_id:
        params["edition_id"] = edition_id
        
    client = get_open_pecha_client()
    http_client = client.get_async_httpx_client()
    response = await get_with_retry(http_client, "/v2/content-search", params=params)
    response.raise_for_status()
    return response.json()
