from typing import Set
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.search.search_openpecha_service import get_multilingual_search_results

TEXT_ID = "BxD11EMUttisysWt8JUyi"
EDITION_ID = "EFN4ITwQp82MKaPxkzP5c"
STALE_TEXT_ID = "xCUSPOGD5e7xjNJ5ltNQG"
STALE_EDITION_ID = "fMn23KrETkcU9B0m47pQq"


def _get_mock_content_search_response_():
    """Payload shape returned by OpenPecha GET /v2/content-search."""
    return [
        {
            "text_id": TEXT_ID,
            "edition_id": EDITION_ID,
            "segment_ids": ["u8TdJavkWlgv56IL40n0w"],
            "context_span": {"start": 539000, "end": 539118},
            "match_span": {"start": 539016, "end": 539019},
            "score": 3.0705519,
            "context": "May all beings hear the sound of Dharma",
        },
    ]


def _get_mock_stale_content_search_hit_():
    """A hit whose edition was deleted from the graph but lingers in the index."""
    return {
        "text_id": STALE_TEXT_ID,
        "edition_id": STALE_EDITION_ID,
        "segment_ids": ["YJC0Uw37wnPUCxUdVTf5I"],
        "context_span": {"start": 1000, "end": 1100},
        "match_span": {"start": 1010, "end": 1016},
        "score": 9.0,
        "context": "Upon hearing those sounds, the sentient beings are moved",
    }


def _mock_edition_lookup_(live_edition_ids: Set[str]):
    """Stand-in for the OpenPecha edition lookup used to drop stale index hits."""

    async def _fetch(edition_id: str):
        if edition_id in live_edition_ids:
            return TEXT_ID
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Edition with id '{edition_id}' not found",
        )

    return patch(
        "pecha_api.search.search_service.fetch_edition_text_id",
        new=AsyncMock(side_effect=_fetch),
    )


def _get_mock_text_payload_():
    """Payload shape returned by OpenPecha GET /v2/texts/{text_id}."""
    return {
        "id": TEXT_ID,
        "language": "en",
        "title": {"en": "The Way of the Bodhisattva"},
        "alt_titles": [],
        "date": "2025-04-05",
        "license": "public",
    }


@pytest.mark.asyncio
async def test_text_id_is_forwarded_upstream_as_text_id():
    """`text_id` and `edition_id` are distinct upstream ids: a text_id sent in the
    edition_id slot matches nothing, which is what emptied "search in this text"."""
    with patch(
        "pecha_api.search.search_openpecha_service.search_by_content",
        new_callable=AsyncMock,
        return_value=_get_mock_content_search_response_(),
    ) as mock_search_by_content, patch(
        "pecha_api.search.search_service.fetch_text_by_id",
        new_callable=AsyncMock,
        return_value=_get_mock_text_payload_(),
    ), _mock_edition_lookup_({EDITION_ID}):
        await get_multilingual_search_results(
            query="buddha", search_type="exact", text_id=TEXT_ID, skip=0, limit=10
        )

    kwargs = mock_search_by_content.await_args.kwargs
    assert kwargs["text_id"] == TEXT_ID
    assert kwargs["edition_id"] is None


@pytest.mark.asyncio
async def test_edition_id_is_forwarded_upstream_as_edition_id():
    """Callers holding an edition id can still narrow the search to that edition."""
    with patch(
        "pecha_api.search.search_openpecha_service.search_by_content",
        new_callable=AsyncMock,
        return_value=_get_mock_content_search_response_(),
    ) as mock_search_by_content, patch(
        "pecha_api.search.search_service.fetch_text_by_id",
        new_callable=AsyncMock,
        return_value=_get_mock_text_payload_(),
    ), _mock_edition_lookup_({EDITION_ID}):
        await get_multilingual_search_results(
            query="buddha", search_type="exact", edition_id=EDITION_ID, skip=0, limit=10
        )

    kwargs = mock_search_by_content.await_args.kwargs
    assert kwargs["edition_id"] == EDITION_ID
    assert kwargs["text_id"] is None


@pytest.mark.asyncio
async def test_no_scope_filter_is_sent_when_no_id_is_given():
    with patch(
        "pecha_api.search.search_openpecha_service.search_by_content",
        new_callable=AsyncMock,
        return_value=[],
    ) as mock_search_by_content:
        response = await get_multilingual_search_results(query="buddha", skip=0, limit=10)

    kwargs = mock_search_by_content.await_args.kwargs
    assert kwargs["text_id"] is None
    assert kwargs["edition_id"] is None
    assert response.sources == []
    assert response.total == 0


@pytest.mark.asyncio
async def test_results_are_grouped_by_edition_and_report_the_edition_id():
    """Filtering is by edition, and the response reports the edition id as text_id
    (metadata is still fetched from OpenPecha by the real upstream text id)."""
    with patch(
        "pecha_api.search.search_openpecha_service.search_by_content",
        new_callable=AsyncMock,
        return_value=_get_mock_content_search_response_(),
    ), patch(
        "pecha_api.search.search_service.fetch_text_by_id",
        new_callable=AsyncMock,
        return_value=_get_mock_text_payload_(),
    ), _mock_edition_lookup_({EDITION_ID}):
        response = await get_multilingual_search_results(
            query="buddha", text_id=EDITION_ID, skip=0, limit=10
        )

    assert len(response.sources) == 1
    assert response.sources[0].text.text_id == EDITION_ID
    assert response.sources[0].segment_matches[0].pecha_segment_id == "u8TdJavkWlgv56IL40n0w"


@pytest.mark.asyncio
async def test_empty_upstream_result_returns_empty_response():
    with patch(
        "pecha_api.search.search_openpecha_service.search_by_content",
        new_callable=AsyncMock,
        return_value=[],
    ):
        response = await get_multilingual_search_results(
            query="buddha", text_id=EDITION_ID, skip=0, limit=10
        )

    assert response.query == "buddha"
    assert response.sources == []
    assert response.total == 0


@pytest.mark.asyncio
async def test_hits_for_editions_missing_from_openpecha_are_dropped():
    """The content-search index outlives deleted editions; those hits would 404
    on POST /texts/{edition_id}/details as soon as a reader clicked them."""
    with patch(
        "pecha_api.search.search_openpecha_service.search_by_content",
        new_callable=AsyncMock,
        return_value=[
            _get_mock_stale_content_search_hit_(),
            *_get_mock_content_search_response_(),
        ],
    ), patch(
        "pecha_api.search.search_service.fetch_text_by_id",
        new_callable=AsyncMock,
        return_value=_get_mock_text_payload_(),
    ), _mock_edition_lookup_({EDITION_ID}):
        response = await get_multilingual_search_results(query="buddha", skip=0, limit=10)

    assert [source.text.text_id for source in response.sources] == [EDITION_ID]
    assert response.total == 1


@pytest.mark.asyncio
async def test_all_editions_missing_returns_an_empty_response():
    with patch(
        "pecha_api.search.search_openpecha_service.search_by_content",
        new_callable=AsyncMock,
        return_value=[_get_mock_stale_content_search_hit_()],
    ), patch(
        "pecha_api.search.search_service.fetch_text_by_id",
        new_callable=AsyncMock,
        return_value=_get_mock_text_payload_(),
    ), _mock_edition_lookup_(set()):
        response = await get_multilingual_search_results(query="buddha", skip=0, limit=10)

    assert response.sources == []
    assert response.total == 0


@pytest.mark.asyncio
async def test_upstream_failure_on_the_edition_check_keeps_the_result():
    """A blip verifying editions must not silently empty a page of results."""
    with patch(
        "pecha_api.search.search_openpecha_service.search_by_content",
        new_callable=AsyncMock,
        return_value=_get_mock_content_search_response_(),
    ), patch(
        "pecha_api.search.search_service.fetch_text_by_id",
        new_callable=AsyncMock,
        return_value=_get_mock_text_payload_(),
    ), patch(
        "pecha_api.search.search_service.fetch_edition_text_id",
        new_callable=AsyncMock,
        side_effect=HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="upstream is down"
        ),
    ):
        response = await get_multilingual_search_results(query="buddha", skip=0, limit=10)

    assert [source.text.text_id for source in response.sources] == [EDITION_ID]
