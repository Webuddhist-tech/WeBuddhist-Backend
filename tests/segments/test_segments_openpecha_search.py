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
    bodies = {"s1": "body of s1", "s2": "body of s2"}

    async def content(segment_id):
        return bodies[segment_id]

    with patch(f"{MODULE}.search_by_content", new_callable=AsyncMock, return_value=hits) as search,          patch(f"{MODULE}.fetch_segment_content_safe", side_effect=content):
        response = await search_segments_by_content_service(SegmentSearchRequest(content="refuge"))

    search.assert_awaited_once_with(query="refuge", limit=20)
    # Each segment carries its own body, not the hit's shared snippet.
    assert [(s.id, s.pecha_segment_id, s.text_id, s.content) for s in response.segments] == [
        ("s1", "s1", "t2", "body of s1"),
        ("s2", "s2", "t2", "body of s2"),
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


@pytest.mark.asyncio
async def test_leaves_out_segments_whose_content_cannot_be_fetched():
    hits = [{"score": 0.9, "context": "snippet", "text_id": "t1", "edition_id": "e1", "segment_ids": ["s1", "s2"]}]

    async def content(segment_id):
        return None if segment_id == "s1" else "body of s2"

    with patch(f"{MODULE}.search_by_content", new_callable=AsyncMock, return_value=hits),          patch(f"{MODULE}.fetch_segment_content_safe", side_effect=content):
        response = await search_segments_by_content_service(SegmentSearchRequest(content="refuge"))

    assert [(s.id, s.content) for s in response.segments] == [("s2", "body of s2")]
