import asyncio
import logging
from typing import List, Optional

from openpecha_api.segments.openpecha_segment_service import fetch_segment_content, fetch_segment_reference

from ..plans_enums import ContentType

logger = logging.getLogger(__name__)


async def _fetch_segment_content_safe(segment_id: str) -> Optional[str]:
    try:
        return await fetch_segment_content(segment_id)
    except Exception:
        logger.exception("Failed to fetch segment content '%s' from openpecha", segment_id)
        return None


async def _fetch_segment_reference_safe(segment_id: str) -> Optional[str]:
    try:
        return await fetch_segment_reference(segment_id)
    except Exception:
        logger.exception("Failed to fetch segment reference '%s' from openpecha", segment_id)
        return None


async def resolve_subtask_content(
    content_type,
    content: Optional[str],
    segment_ids: Optional[List[str]],
) -> Optional[str]:
    """Live-resolve SOURCE_REFERENCE subtask content from openpecha segments.

    Falls back to the stored `content` value when segment_ids are absent or
    the content type isn't SOURCE_REFERENCE. Segments that fail to resolve
    (invalid id or upstream miss) are skipped rather than discarding the
    whole result, so one bad id doesn't blank out the other valid segments.
    Only falls back to the stored `content` if none of the segments resolve.
    """
    if content_type != ContentType.SOURCE_REFERENCE or not segment_ids:
        return content

    segment_contents = await asyncio.gather(
        *[_fetch_segment_content_safe(segment_id) for segment_id in segment_ids]
    )

    resolved_contents = [
        segment_content for segment_content in segment_contents if segment_content is not None
    ]

    if not resolved_contents:
        return content

    return "\n".join(resolved_contents)


async def resolve_subtasks_content(subtasks) -> List[Optional[str]]:
    """Resolve content for a list of subtask-like objects, preserving order."""
    return await asyncio.gather(
        *[
            resolve_subtask_content(sub_task.content_type, sub_task.content, sub_task.segment_ids)
            for sub_task in subtasks
        ]
    )


async def resolve_subtask_refs(
    content_type,
    segment_ids: Optional[List[str]],
) -> Optional[List[Optional[str]]]:
    """Fetch the openpecha reference label for each segment of a SOURCE_REFERENCE subtask.

    Index-aligned with segment_ids so callers can line refs up against
    segment_ids/segment_numbers. A segment that fails to resolve comes back
    as None at its position rather than shifting the rest of the list.
    """
    if content_type != ContentType.SOURCE_REFERENCE or not segment_ids:
        return None

    return list(
        await asyncio.gather(
            *[_fetch_segment_reference_safe(segment_id) for segment_id in segment_ids]
        )
    )


async def resolve_subtasks_refs(subtasks) -> List[Optional[List[Optional[str]]]]:
    """Resolve per-segment openpecha refs for a list of subtask-like objects, preserving order."""
    return await asyncio.gather(
        *[
            resolve_subtask_refs(sub_task.content_type, sub_task.segment_ids)
            for sub_task in subtasks
        ]
    )
