from typing import Any, Dict, Optional

from pecha_api.external_clients import get_open_pecha_client, get_with_retry

async def fetch_related_segments(
    segment_id: str,
    limit: int = 10,
    offset: int = 0,
    text_id: Optional[str] = None,
) -> Dict[str, Any]:

    params: Dict[str, Any] = {
        "limit": limit,
        "offset": offset,
    }
    if text_id:
        params["text_id"] = text_id
    client = get_open_pecha_client()
    http_client = client.get_async_httpx_client()
    response = await get_with_retry(
        http_client,
        f"/v2/segments/{segment_id}/related",
        params=params,
    )
    response.raise_for_status()
    return response.json()


async def fetch_segment_content(segment_id: str) -> Optional[str]:
    client = get_open_pecha_client()
    http_client = client.get_async_httpx_client()
    response = await get_with_retry(http_client, f"/v2/segments/{segment_id}/content")
    response.raise_for_status()
    data = response.json()
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ("content", "text", "value"):
            value = data.get(key)
            if isinstance(value, str):
                return value
    return None

async def fetch_segment_details(segment_id:str) :
    client = get_open_pecha_client()
    http_client = client.get_async_httpx_client()
    response = await get_with_retry(http_client, f"/v2/segments/{segment_id}")
    response.raise_for_status()
    return response.json()

def _extract_segment_reference(segment_details: Dict[str, Any]) -> Optional[str]:
    if not isinstance(segment_details, dict):
        return None
    reference = segment_details.get("reference")
    if isinstance(reference, str) and reference:
        return reference
    lines = segment_details.get("lines")
    if isinstance(lines, list):
        for line in lines:
            if isinstance(line, dict):
                line_reference = line.get("reference")
                if isinstance(line_reference, str) and line_reference:
                    return line_reference
    return None

async def fetch_segment_reference(segment_id: str) -> Optional[str]:
    segment_details = await fetch_segment_details(segment_id)
    return _extract_segment_reference(segment_details)
