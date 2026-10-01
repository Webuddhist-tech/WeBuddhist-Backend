"""The read-back path: audio must surface on the item DTO, ordered and
presigned, on BOTH the CMS and the public collection detail.

Each service keeps its own copy of _build_items_dto, so both are exercised
here against the real builder rather than a mocked one.
"""
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4
from datetime import datetime, timezone as tz

from pecha_api.group_recitation_collection import cms_service, service

CMS = "pecha_api.group_recitation_collection.cms_service"
PUBLIC = "pecha_api.group_recitation_collection.service"
ASSET_SERVICE = "pecha_api.group_assets.service"


class MockItem:
    def __init__(self, text_id="t-1", display_order=1):
        self.id = uuid4()
        self.text_id = text_id
        self.display_order = display_order


class MockText:
    def __init__(self, title="Heart Sutra", language="en"):
        self.title = title
        self.language = language


class MockAssetType:
    value = "AUDIO"


class MockAsset:
    def __init__(self, title):
        self.id = uuid4()
        self.group_id = uuid4()
        self.asset_type = MockAssetType()
        self.title = title
        self.file_name = f"{title}.mp3"
        self.s3_key = f"groups/{self.group_id}/assets/audio/{uuid4()}.mp3"
        self.mime_type = "audio/mpeg"
        self.file_size_bytes = 2947188
        self.duration_ms = 184000
        self.created_at = datetime.now(tz.utc)


@pytest.mark.parametrize("module,name", [(cms_service, CMS), (service, PUBLIC)])
class TestBuildItemsDtoAudio:
    @pytest.mark.asyncio
    async def test_audio_is_ordered_and_presigned(self, module, name):
        item = MockItem()
        slow, fast = MockAsset("slow"), MockAsset("fast")

        with patch(
            f"{name}.get_texts_by_edition_or_text_ids",
            return_value={"t-1": MockText()},
        ), patch(
            f"{name}.get_assets_for_items", return_value={item.id: [slow, fast]}
        ), patch(
            f"{ASSET_SERVICE}.generate_asset_presigned_url",
            return_value="https://presigned",
        ):
            dto = await module._build_items_dto([item], db=MagicMock())

        assert len(dto) == 1
        assert [a.title for a in dto[0].audio] == ["slow", "fast"]
        assert all(a.asset_url == "https://presigned" for a in dto[0].audio)

    @pytest.mark.asyncio
    async def test_s3_key_is_never_exposed(self, module, name):
        item = MockItem()

        with patch(
            f"{name}.get_texts_by_edition_or_text_ids",
            return_value={"t-1": MockText()},
        ), patch(
            f"{name}.get_assets_for_items",
            return_value={item.id: [MockAsset("slow")]},
        ), patch(
            f"{ASSET_SERVICE}.generate_asset_presigned_url",
            return_value="https://presigned",
        ):
            dto = await module._build_items_dto([item], db=MagicMock())

        assert "s3_key" not in dto[0].audio[0].model_dump()

    @pytest.mark.asyncio
    async def test_item_without_audio_gets_empty_list(self, module, name):
        item = MockItem()

        with patch(
            f"{name}.get_texts_by_edition_or_text_ids",
            return_value={"t-1": MockText()},
        ), patch(f"{name}.get_assets_for_items", return_value={}):
            dto = await module._build_items_dto([item], db=MagicMock())

        assert dto[0].audio == []

    @pytest.mark.asyncio
    async def test_audio_is_fetched_in_one_batched_query(self, module, name):
        """Never a query per item: one call, all item ids."""
        items = [MockItem(f"t-{i}", i) for i in range(1, 6)]

        with patch(
            f"{name}.get_texts_by_edition_or_text_ids",
            return_value={f"t-{i}": MockText() for i in range(1, 6)},
        ), patch(
            f"{name}.get_assets_for_items", return_value={}
        ) as mock_batch:
            await module._build_items_dto(items, db=MagicMock())

        mock_batch.assert_called_once()
        assert len(mock_batch.call_args.kwargs["item_ids"]) == 5

    @pytest.mark.asyncio
    async def test_no_db_means_no_audio_and_no_crash(self, module, name):
        """Callers that pass no session still build items, just without audio."""
        item = MockItem()

        with patch(
            f"{name}.get_texts_by_edition_or_text_ids",
            return_value={"t-1": MockText()},
        ):
            dto = await module._build_items_dto([item])

        assert dto[0].audio == []
