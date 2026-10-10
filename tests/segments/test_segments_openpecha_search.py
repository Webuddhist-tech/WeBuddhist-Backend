from unittest.mock import AsyncMock, patch

import pytest

from pecha_api.texts.segments.segments_enum import SegmentType
from pecha_api.texts.segments.segments_openpecha_service import (
    search_segments_by_content_service,
)
from pecha_api.texts.segments.segments_response_models import SegmentSearchRequest

MODULE = "pecha_api.texts.segments.segments_openpecha_service"


@pytest.mark.asyncio
async def test_maps_openpecha_hits_to_segments():
    hits = [
        {"score": 0.4, "context": "weaker", "text_id": "t1", "edition_id": "e1", "segment_ids": ["s1"]},
        {"score": 0.9, "context": "best", "text_id": "t2", "edition_id": "e2", "segment_ids": ["s2", "s1"]},
    ]
    with patch(f"{MODULE}.search_by_content", new_callable=AsyncMock, return_value=hits) as search:
        response = await search_segments_by_content_service(SegmentSearchRequest(content="refuge"))

    search.assert_awaited_once_with(query="refuge", limit=20)
    assert [(s.id, s.pecha_segment_id, s.text_id, s.content) for s in response.segments] == [
        ("s1", "s1", "t2", "best"),
        ("s2", "s2", "t2", "best"),
    ]
    assert all(s.type == SegmentType.SOURCE for s in response.segments)


@pytest.mark.asyncio
async def test_empty_when_openpecha_fails():
    with patch(f"{MODULE}.search_by_content", new_callable=AsyncMock, side_effect=RuntimeError("down")):
        response = await search_segments_by_content_service(SegmentSearchRequest(content="refuge"))

    assert response.segments == []


@pytest.mark.asyncio
async def test_empty_on_unexpected_response():
    with patch(f"{MODULE}.search_by_content", new_callable=AsyncMock, return_value={"error": "x"}):
        response = await search_segments_by_content_service(SegmentSearchRequest(content="refuge"))

    assert response.segments == []
