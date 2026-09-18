import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
from datetime import datetime, timezone as tz
from fastapi import HTTPException
from starlette import status

from pecha_api.group_assets.enums import GroupAssetType
from pecha_api.group_assets.item_assets_service import (
    MAX_AUDIO_ASSETS_PER_ITEM,
    set_item_audio_service,
)

SERVICE = "pecha_api.group_assets.item_assets_service"
CMS_SERVICE = "pecha_api.group_recitation_collection.cms_service"


class MockAuthor:
    def __init__(self, email="author@example.com"):
        self.id = uuid4()
        self.email = email


class MockAsset:
    def __init__(self, id=None, asset_type=GroupAssetType.AUDIO):
        self.id = id or uuid4()
        self.asset_type = asset_type


class MockCollection:
    def __init__(self, id=None, group_id=None):
        self.id = id or uuid4()
        self.group_id = group_id or uuid4()
        self.name = "TCV Morning Prayers"
        self.img_url = None
        self.created_at = datetime.now(tz.utc)


class MockItem:
    def __init__(self, id=None):
        self.id = id or uuid4()
        self.text_id = str(uuid4())
        self.display_order = 1


def _patch_happy_path(mock_author, mock_group, mock_collection, mock_item):
    """Wire the shared auth/lookup mocks every case needs."""
    mock_author.return_value = MockAuthor()
    mock_group.return_value = MagicMock()
    collection = MockCollection()
    mock_collection.return_value = collection
    mock_item.return_value = MockItem()
    return collection


class TestSetItemAudioValidation:
    @pytest.mark.asyncio
    async def test_duplicate_asset_ids_rejected(self):
        asset_id = uuid4()
        with pytest.raises(HTTPException) as exc:
            await set_item_audio_service(
                token="token",
                group_id=uuid4(),
                collection_id=uuid4(),
                item_id=uuid4(),
                asset_ids=[asset_id, asset_id],
            )
        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST

    @pytest.mark.asyncio
    async def test_more_than_max_assets_rejected(self):
        with pytest.raises(HTTPException) as exc:
            await set_item_audio_service(
                token="token",
                group_id=uuid4(),
                collection_id=uuid4(),
                item_id=uuid4(),
                asset_ids=[uuid4() for _ in range(MAX_AUDIO_ASSETS_PER_ITEM + 1)],
            )
        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


class TestSetItemAudioService:
    @patch(f"{CMS_SERVICE}._build_items_dto", new_callable=AsyncMock)
    @patch(f"{SERVICE}.get_collection_items")
    @patch(f"{SERVICE}.replace_item_assets")
    @patch(f"{SERVICE}.GroupRecitationCollectionItemAsset")
    @patch(f"{SERVICE}.get_assets_by_ids")
    @patch(f"{SERVICE}.get_collection_item_by_id")
    @patch(f"{SERVICE}.get_collection_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @pytest.mark.asyncio
    async def test_links_assets_in_sent_order(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_collection,
        mock_item,
        mock_get_assets,
        mock_link_model,
        mock_replace,
        mock_items,
        mock_build,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        _patch_happy_path(mock_author, mock_group, mock_collection, mock_item)
        a, b = MockAsset(), MockAsset()
        mock_get_assets.return_value = [a, b]
        mock_items.return_value = []
        mock_build.return_value = []

        await set_item_audio_service(
            token="token",
            group_id=uuid4(),
            collection_id=uuid4(),
            item_id=uuid4(),
            asset_ids=[a.id, b.id],
        )

        # display_order is the array index, 1-based, in the order sent.
        orders = [c.kwargs["display_order"] for c in mock_link_model.call_args_list]
        asset_order = [c.kwargs["asset_id"] for c in mock_link_model.call_args_list]
        assert orders == [1, 2]
        assert asset_order == [a.id, b.id]

    @patch(f"{CMS_SERVICE}._build_items_dto", new_callable=AsyncMock)
    @patch(f"{SERVICE}.get_collection_items")
    @patch(f"{SERVICE}.replace_item_assets")
    @patch(f"{SERVICE}.get_collection_item_by_id")
    @patch(f"{SERVICE}.get_collection_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @pytest.mark.asyncio
    async def test_empty_array_clears_links(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_collection,
        mock_item,
        mock_replace,
        mock_items,
        mock_build,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        _patch_happy_path(mock_author, mock_group, mock_collection, mock_item)
        mock_items.return_value = []
        mock_build.return_value = []

        await set_item_audio_service(
            token="token",
            group_id=uuid4(),
            collection_id=uuid4(),
            item_id=uuid4(),
            asset_ids=[],
        )

        # Replaces with an empty set; the assets stay in the library.
        assert mock_replace.call_args.kwargs["links"] == []

    @patch(f"{SERVICE}.get_assets_by_ids")
    @patch(f"{SERVICE}.get_collection_item_by_id")
    @patch(f"{SERVICE}.get_collection_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @pytest.mark.asyncio
    async def test_asset_from_another_group_is_404_not_403(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_collection,
        mock_item,
        mock_get_assets,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        _patch_happy_path(mock_author, mock_group, mock_collection, mock_item)
        # Group-scoped query returns nothing for a foreign asset.
        mock_get_assets.return_value = []

        with pytest.raises(HTTPException) as exc:
            await set_item_audio_service(
                token="token",
                group_id=uuid4(),
                collection_id=uuid4(),
                item_id=uuid4(),
                asset_ids=[uuid4()],
            )

        assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    @patch(f"{SERVICE}.get_assets_by_ids")
    @patch(f"{SERVICE}.get_collection_item_by_id")
    @patch(f"{SERVICE}.get_collection_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @pytest.mark.asyncio
    async def test_non_audio_asset_rejected(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_collection,
        mock_item,
        mock_get_assets,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        _patch_happy_path(mock_author, mock_group, mock_collection, mock_item)
        image = MockAsset(asset_type=GroupAssetType.IMAGE)
        mock_get_assets.return_value = [image]

        with pytest.raises(HTTPException) as exc:
            await set_item_audio_service(
                token="token",
                group_id=uuid4(),
                collection_id=uuid4(),
                item_id=uuid4(),
                asset_ids=[image.id],
            )

        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST

    @patch(f"{SERVICE}.get_collection_item_by_id")
    @patch(f"{SERVICE}.get_collection_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @pytest.mark.asyncio
    async def test_missing_item_is_404(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_collection,
        mock_item,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_collection.return_value = MockCollection()
        mock_item.return_value = None

        with pytest.raises(HTTPException) as exc:
            await set_item_audio_service(
                token="token",
                group_id=uuid4(),
                collection_id=uuid4(),
                item_id=uuid4(),
                asset_ids=[],
            )

        assert exc.value.status_code == status.HTTP_404_NOT_FOUND
