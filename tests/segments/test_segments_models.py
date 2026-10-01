import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pecha_api.texts.segments.segments_models import Segment


class _AsyncCursor:
    def __init__(self, documents):
        self._documents = documents
        self._index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._index >= len(self._documents):
            raise StopAsyncIteration
        document = self._documents[self._index]
        self._index += 1
        return document


SEGMENT_UUID = "efb26a06-f373-450b-ba57-e7a8d4dd5b64"


@pytest.mark.asyncio
async def test_get_segment_by_pecha_segment_id_uses_dict_query():
    mock_segment = MagicMock()

    with patch.object(
        Segment, "find_one", new_callable=AsyncMock, return_value=mock_segment
    ) as mock_find_one:
        result = await Segment.get_segment_by_pecha_segment_id(
            pecha_segment_id="pecha-seg-1"
        )

    mock_find_one.assert_awaited_once_with({"pecha_segment_id": "pecha-seg-1"})
    assert result is mock_segment


def test_partition_segment_identifiers_splits_uuids_and_pecha_ids():
    uuids, pecha_ids = Segment._partition_segment_identifiers(
        [SEGMENT_UUID, "pecha-seg-1", "", SEGMENT_UUID, "pecha-seg-1"]
    )

    assert uuids == [uuid.UUID(SEGMENT_UUID)]
    assert pecha_ids == ["pecha-seg-1"]


def test_partition_segment_identifiers_treats_non_uuid_strings_as_pecha_ids():
    uuids, pecha_ids = Segment._partition_segment_identifiers(["not-a-uuid", "pecha-seg-2"])

    assert uuids == []
    assert pecha_ids == ["not-a-uuid", "pecha-seg-2"]


def test_partition_segment_identifiers_skips_empty_values():
    uuids, pecha_ids = Segment._partition_segment_identifiers(["", SEGMENT_UUID])

    assert uuids == [uuid.UUID(SEGMENT_UUID)]
    assert pecha_ids == []


@pytest.mark.asyncio
async def test_load_projected_segment_contents_loads_uuid_segments_via_beanie_find():
    segment_id = uuid.UUID(SEGMENT_UUID)
    mock_segment = MagicMock()
    mock_segment.id = segment_id
    mock_segment.text_id = "text-1"
    mock_segment.content = "segment content"

    mock_find = MagicMock()
    mock_find.to_list = AsyncMock(return_value=[mock_segment])

    with patch.object(Segment, "find", return_value=mock_find) as mock_find_call:
        result = await Segment._load_projected_segment_contents(
            segment_uuids=[segment_id],
            pecha_segment_ids=[],
        )

    mock_find_call.assert_called_once_with({"_id": {"$in": [segment_id]}})
    assert result == {SEGMENT_UUID: ("text-1", "segment content")}


@pytest.mark.asyncio
async def test_load_projected_segment_contents_loads_pecha_segment_ids_via_motor():
    mock_collection = MagicMock()
    mock_collection.find.return_value = _AsyncCursor(
        [
            {"pecha_segment_id": "pecha-seg-1", "text_id": "text-1", "content": "content-1"},
            {"text_id": "text-2", "content": "content-2"},
        ]
    )

    with patch.object(Segment, "get_motor_collection", return_value=mock_collection):
        result = await Segment._load_projected_segment_contents(
            segment_uuids=[],
            pecha_segment_ids=["pecha-seg-1"],
        )

    mock_collection.find.assert_called_once_with(
        {"pecha_segment_id": {"$in": ["pecha-seg-1"]}},
        {"text_id": 1, "content": 1, "pecha_segment_id": 1},
    )
    assert result == {"pecha-seg-1": ("text-1", "content-1")}


@pytest.mark.asyncio
async def test_load_projected_segment_contents_merges_uuid_and_pecha_results():
    segment_id = uuid.UUID(SEGMENT_UUID)
    mock_segment = MagicMock()
    mock_segment.id = segment_id
    mock_segment.text_id = "text-uuid"
    mock_segment.content = "uuid content"

    mock_find = MagicMock()
    mock_find.to_list = AsyncMock(return_value=[mock_segment])

    mock_collection = MagicMock()
    mock_collection.find.return_value = _AsyncCursor(
        [{"pecha_segment_id": "pecha-seg-1", "text_id": "text-pecha", "content": "pecha content"}]
    )

    with patch.object(Segment, "find", return_value=mock_find), patch.object(
        Segment, "get_motor_collection", return_value=mock_collection
    ):
        result = await Segment._load_projected_segment_contents(
            segment_uuids=[segment_id],
            pecha_segment_ids=["pecha-seg-1"],
        )

    assert result == {
        SEGMENT_UUID: ("text-uuid", "uuid content"),
        "pecha-seg-1": ("text-pecha", "pecha content"),
    }


@pytest.mark.asyncio
async def test_get_segment_contents_by_ids_returns_empty_for_empty_input():
    assert await Segment.get_segment_contents_by_ids([]) == {}


@pytest.mark.asyncio
async def test_get_segment_contents_by_ids_partitions_and_loads_contents():
    expected = {SEGMENT_UUID: ("text-1", "content")}

    with patch.object(
        Segment,
        "_load_projected_segment_contents",
        new_callable=AsyncMock,
        return_value=expected,
    ) as mock_load:
        result = await Segment.get_segment_contents_by_ids([SEGMENT_UUID, "pecha-seg-1"])

    assert result == expected
    mock_load.assert_awaited_once_with(
        segment_uuids=[uuid.UUID(SEGMENT_UUID)],
        pecha_segment_ids=["pecha-seg-1"],
    )


@pytest.mark.asyncio
async def test_get_version_translation_contents_by_parent_ids_returns_empty_for_missing_input():
    assert await Segment.get_version_translation_contents_by_parent_ids([], "text-1") == {}
    assert await Segment.get_version_translation_contents_by_parent_ids(["seg-1"], "") == {}


@pytest.mark.asyncio
async def test_get_version_translation_contents_by_parent_ids_maps_parent_segments():
    mock_collection = MagicMock()
    mock_collection.find.return_value = _AsyncCursor(
        [
            {
                "content": "translation one",
                "mapping": [{"segments": ["parent-seg-1", "other-seg"]}],
            },
            {
                "content": "translation two",
                "mapping": [{"segments": ["parent-seg-2"]}],
            },
        ]
    )

    with patch.object(Segment, "get_motor_collection", return_value=mock_collection):
        result = await Segment.get_version_translation_contents_by_parent_ids(
            parent_segment_ids=["parent-seg-1", "parent-seg-2"],
            version_text_id="version-text-1",
        )

    mock_collection.find.assert_called_once_with(
        {
            "text_id": "version-text-1",
            "mapping": {"$elemMatch": {"segments": {"$in": ["parent-seg-1", "parent-seg-2"]}}},
        },
        {"content": 1, "mapping": 1},
    )
    assert result == {
        "parent-seg-1": "translation one",
        "parent-seg-2": "translation two",
    }
