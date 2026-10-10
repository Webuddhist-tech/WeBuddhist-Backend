"""Tag segments are OpenPecha segments, referenced by their OpenPecha id."""

import asyncio
import logging
from typing import List, Optional

import httpx
from fastapi import HTTPException
from starlette import status

from openpecha_api.segments.openpecha_segment_service import fetch_segment_details
from pecha_api.plans.shared.subtask_content_resolver import fetch_segment_content_safe
from pecha_api.plans.tags.tag_response_models import SegmentContentDTO

logger = logging.getLogger(__name__)


async def _segment_exists(segment_id: str) -> bool:
    try:
        await fetch_segment_details(segment_id)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == status.HTTP_404_NOT_FOUND:
            return False
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to check segments with upstream service",
        )
    except Exception:
        logger.exception("Failed to check openpecha segment %s", segment_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to check segments with upstream service",
        )
    return True


async def validate_segment_ids(segment_ids: List[str]) -> None:
    """400 for the first id OpenPecha doesn't know; 502 if it can't be asked."""
    if not segment_ids:
        return
    unique_segment_ids = list(dict.fromkeys(segment_ids))
    exists = await asyncio.gather(*[_segment_exists(segment_id) for segment_id in unique_segment_ids])
    for segment_id, found in zip(unique_segment_ids, exists):
        if not found:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Segment with id '{segment_id}' does not exist",
            )


async def _fetch_segment_text_id(segment_id: str) -> str:
    try:
        details = await fetch_segment_details(segment_id)
    except Exception:
        logger.warning("Failed to fetch openpecha segment details for %s", segment_id, exc_info=True)
        return ""
    text_id = details.get("text_id") if isinstance(details, dict) else None
    return text_id or ""


async def _fetch_tag_segment(segment_id: str) -> Optional[SegmentContentDTO]:
    content, text_id = await asyncio.gather(
        fetch_segment_content_safe(segment_id),
        _fetch_segment_text_id(segment_id),
    )
    if content is None:
        return None
    return SegmentContentDTO(segment_id=segment_id, text_id=text_id, content=content)


async def fetch_tag_segments(segment_ids: List[str]) -> List[SegmentContentDTO]:
    """The tag's segments in order; ones OpenPecha can't serve are skipped."""
    segments = await asyncio.gather(*[_fetch_tag_segment(segment_id) for segment_id in segment_ids])
    return [segment for segment in segments if segment is not None]
