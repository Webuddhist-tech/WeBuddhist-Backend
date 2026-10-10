from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.plans.tags.tag_segments_openpecha import fetch_tag_segments, validate_segment_ids

MODULE = "pecha_api.plans.tags.tag_segments_openpecha"


def _status_error(code: int) -> httpx.HTTPStatusError:
    return httpx.HTTPStatusError("upstream", request=MagicMock(), response=MagicMock(status_code=code))


@pytest.mark.asyncio
async def test_validate_checks_each_id_once():
    with patch(f"{MODULE}.fetch_segment_details", new_callable=AsyncMock, return_value={"id": "s1"}) as details:
        await validate_segment_ids(["s1", "s1", "s2"])

    assert [call.args[0] for call in details.await_args_list] == ["s1", "s2"]


@pytest.mark.asyncio
async def test_validate_400_for_an_unknown_segment():
    async def details(segment_id):
        if segment_id == "missing":
            raise _status_error(404)
        return {"id": segment_id}

    with patch(f"{MODULE}.fetch_segment_details", side_effect=details):
        with pytest.raises(HTTPException) as exc_info:
            await validate_segment_ids(["s1", "missing"])

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "missing" in exc_info.value.detail


@pytest.mark.asyncio
async def test_validate_502_when_openpecha_fails():
    with patch(f"{MODULE}.fetch_segment_details", new_callable=AsyncMock, side_effect=_status_error(500)):
        with pytest.raises(HTTPException) as exc_info:
            await validate_segment_ids(["s1"])

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY


@pytest.mark.asyncio
async def test_validate_nothing_to_check():
    with patch(f"{MODULE}.fetch_segment_details", new_callable=AsyncMock) as details:
        await validate_segment_ids([])

    details.assert_not_awaited()


@pytest.mark.asyncio
async def test_fetch_keeps_order_and_skips_unresolved_segments():
    contents = {"s1": "first", "s2": None, "s3": "third"}

    async def content(segment_id):
        return contents[segment_id]

    with patch(f"{MODULE}.fetch_segment_content_safe", side_effect=content), \
         patch(f"{MODULE}.fetch_segment_details", new_callable=AsyncMock, return_value={"text_id": "t1"}):
        segments = await fetch_tag_segments(["s1", "s2", "s3"])

    assert [(s.segment_id, s.text_id, s.content) for s in segments] == [
        ("s1", "t1", "first"),
        ("s3", "t1", "third"),
    ]


@pytest.mark.asyncio
async def test_fetch_keeps_content_when_details_fail():
    with patch(f"{MODULE}.fetch_segment_content_safe", new_callable=AsyncMock, return_value="body"), \
         patch(f"{MODULE}.fetch_segment_details", new_callable=AsyncMock, side_effect=RuntimeError("down")):
        segments = await fetch_tag_segments(["s1"])

    assert [(s.segment_id, s.text_id, s.content) for s in segments] == [("s1", "", "body")]
