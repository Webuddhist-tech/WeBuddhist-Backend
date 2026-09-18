import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from uuid import uuid4
from datetime import datetime, timezone as tz
from fastapi import HTTPException
from starlette import status

from pecha_api.group_assets.enums import GroupAssetType
from pecha_api.group_assets.response_models import (
    GroupAssetsResponse,
    UpdateGroupAssetRequest,
)
from pecha_api.group_assets.service import (
    delete_group_asset_service,
    list_group_assets_service,
    update_group_asset_service,
    upload_group_asset_service,
    validate_audio_file,
)

SERVICE = "pecha_api.group_assets.service"


class MockGroupAsset:
    """Mock GroupAsset model."""

    def __init__(
        self,
        id=None,
        group_id=None,
        title="Heart Sutra",
        asset_type=GroupAssetType.AUDIO,
        s3_key=None,
        file_name="heart-sutra.mp3",
    ):
        self.id = id or uuid4()
        self.group_id = group_id or uuid4()
        self.asset_type = asset_type
        self.title = title
        self.s3_key = s3_key or f"groups/{self.group_id}/assets/audio/{uuid4()}.mp3"
        self.file_name = file_name
        self.mime_type = "audio/mpeg"
        self.file_size_bytes = 2947188
        self.duration_ms = 184000
        self.created_at = datetime.now(tz.utc)
        self.updated_at = None
        self.deleted_at = None
        self.created_by = "author@example.com"
        self.updated_by = None


class MockAuthor:
    def __init__(self, id=None, email="author@example.com"):
        self.id = id or uuid4()
        self.email = email


class MockUploadFile:
    def __init__(self, filename="chant.mp3", size=1024, content_type="audio/mpeg"):
        self.filename = filename
        self.size = size
        self.content_type = content_type
        self.file = MagicMock()


class TestValidateAudioFile:
    def test_accepts_allowed_extension(self):
        validate_audio_file(MockUploadFile(filename="chant.mp3"))

    def test_rejects_non_audio_extension(self):
        with pytest.raises(HTTPException) as exc:
            validate_audio_file(MockUploadFile(filename="notes.pdf"))
        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST

    def test_rejects_oversized_file(self):
        with pytest.raises(HTTPException) as exc:
            validate_audio_file(
                MockUploadFile(filename="chant.mp3", size=60 * 1024 * 1024)
            )
        assert exc.value.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE


class TestUploadGroupAssetService:
    @patch(f"{SERVICE}.generate_asset_presigned_url")
    @patch(f"{SERVICE}.GroupAsset")
    @patch(f"{SERVICE}.create_asset")
    @patch(f"{SERVICE}.upload_file")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    def test_upload_success_uses_group_scoped_key(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_upload,
        mock_create,
        mock_model,
        mock_presign,
    ):
        group_id = uuid4()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_create.return_value = MockGroupAsset(group_id=group_id)
        mock_presign.return_value = "https://presigned"

        result = upload_group_asset_service(
            token="token",
            group_id=group_id,
            file=MockUploadFile(),
            asset_type=GroupAssetType.AUDIO,
        )

        assert result.asset_url == "https://presigned"
        s3_key = mock_upload.call_args.kwargs["s3_key"]
        # Ownership must be legible from the key alone.
        assert s3_key.startswith(f"groups/{group_id}/assets/audio/")

    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    def test_upload_rejects_non_audio_asset_type(self, mock_session, mock_author):
        with pytest.raises(HTTPException) as exc:
            upload_group_asset_service(
                token="token",
                group_id=uuid4(),
                file=MockUploadFile(),
                asset_type=GroupAssetType.IMAGE,
            )
        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST

    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    def test_upload_rejects_bad_format_before_touching_s3(
        self, mock_session, mock_author, mock_group, mock_perm
    ):
        with pytest.raises(HTTPException) as exc:
            upload_group_asset_service(
                token="token",
                group_id=uuid4(),
                file=MockUploadFile(filename="notes.pdf"),
                asset_type=GroupAssetType.AUDIO,
            )
        assert exc.value.status_code == status.HTTP_400_BAD_REQUEST


class TestListGroupAssetsService:
    @patch(f"{SERVICE}.generate_asset_presigned_url")
    @patch(f"{SERVICE}.get_group_assets")
    @patch(f"{SERVICE}.require_can_read_group_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    def test_lists_group_assets_before_anything_is_linked(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_get_assets,
        mock_presign,
    ):
        group_id = uuid4()
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_presign.return_value = "https://presigned"
        mock_get_assets.return_value = (
            [MockGroupAsset(group_id=group_id) for _ in range(3)],
            3,
        )

        result = list_group_assets_service(
            token="token",
            group_id=group_id,
            asset_type=GroupAssetType.AUDIO,
        )

        assert isinstance(result, GroupAssetsResponse)
        assert len(result.assets) == 3
        assert result.total == 3

    @patch(f"{SERVICE}.require_can_read_group_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    def test_missing_group_is_404(
        self, mock_session, mock_author, mock_group, mock_perm
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = None

        with pytest.raises(HTTPException) as exc:
            list_group_assets_service(token="token", group_id=uuid4())
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND


class TestUpdateGroupAssetService:
    @patch(f"{SERVICE}.generate_asset_presigned_url")
    @patch(f"{SERVICE}.update_asset")
    @patch(f"{SERVICE}.get_asset_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    def test_rename_success(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_get,
        mock_update,
        mock_presign,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_presign.return_value = "https://presigned"
        asset = MockGroupAsset()
        mock_get.return_value = asset

        result = update_group_asset_service(
            token="token",
            group_id=uuid4(),
            asset_id=asset.id,
            request=UpdateGroupAssetRequest(title="Heart Sutra - slow"),
        )

        assert result.title == "Heart Sutra - slow"

    @patch(f"{SERVICE}.get_asset_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    def test_asset_from_another_group_is_404(
        self, mock_session, mock_author, mock_group, mock_perm, mock_get
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        # Repository scopes by group, so a foreign asset simply is not found.
        mock_get.return_value = None

        with pytest.raises(HTTPException) as exc:
            update_group_asset_service(
                token="token",
                group_id=uuid4(),
                asset_id=uuid4(),
                request=UpdateGroupAssetRequest(title="x"),
            )
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND


class TestDeleteGroupAssetService:
    @patch(f"{SERVICE}.delete_file")
    @patch(f"{SERVICE}.soft_delete_asset")
    @patch(f"{SERVICE}.get_asset_usages")
    @patch(f"{SERVICE}.get_asset_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @pytest.mark.asyncio
    async def test_delete_unused_asset_succeeds(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_get,
        mock_usages,
        mock_soft_delete,
        mock_delete_file,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_get.return_value = MockGroupAsset()
        mock_usages.return_value = []

        await delete_group_asset_service(
            token="token", group_id=uuid4(), asset_id=uuid4()
        )

        mock_soft_delete.assert_called_once()
        mock_delete_file.assert_called_once()

    @patch(f"{SERVICE}._resolve_text_titles", new_callable=AsyncMock)
    @patch(f"{SERVICE}.get_asset_usages")
    @patch(f"{SERVICE}.get_asset_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @pytest.mark.asyncio
    async def test_delete_linked_asset_returns_409_with_usages(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_get,
        mock_usages,
        mock_titles,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_get.return_value = MockGroupAsset()
        collection_id, item_id = uuid4(), uuid4()
        mock_usages.return_value = [
            (collection_id, "Morning Recitations", item_id, "text-1"),
            (collection_id, "Morning Recitations", uuid4(), "text-2"),
        ]
        mock_titles.return_value = {"text-1": "Heart Sutra", "text-2": "Refuge"}

        with pytest.raises(HTTPException) as exc:
            await delete_group_asset_service(
                token="token", group_id=uuid4(), asset_id=uuid4()
            )

        assert exc.value.status_code == status.HTTP_409_CONFLICT
        assert len(exc.value.detail["usages"]) == 2
        assert exc.value.detail["usages"][0]["collection_name"] == "Morning Recitations"

    @patch(f"{SERVICE}.delete_file")
    @patch(f"{SERVICE}.soft_delete_asset")
    @patch(f"{SERVICE}.delete_links_for_asset")
    @patch(f"{SERVICE}.get_asset_usages")
    @patch(f"{SERVICE}.get_asset_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @pytest.mark.asyncio
    async def test_force_delete_drops_links(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_get,
        mock_usages,
        mock_drop_links,
        mock_soft_delete,
        mock_delete_file,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_get.return_value = MockGroupAsset()
        mock_usages.return_value = [(uuid4(), "Morning", uuid4(), "text-1")]

        await delete_group_asset_service(
            token="token", group_id=uuid4(), asset_id=uuid4(), force=True
        )

        mock_drop_links.assert_called_once()
        mock_soft_delete.assert_called_once()


class TestSoftDeleteClearsLinks:
    """Items and collections are soft-deleted, so the link FK's CASCADE never
    fires; the services must drop the links explicitly."""

    @patch("pecha_api.group_recitation_collection.cms_service.soft_delete_collection_item")
    @patch("pecha_api.group_recitation_collection.cms_service.delete_links_for_item")
    @patch("pecha_api.group_recitation_collection.cms_service.get_collection_item_by_id")
    @patch("pecha_api.group_recitation_collection.cms_service.get_collection_by_id")
    @patch("pecha_api.group_recitation_collection.cms_service.require_can_create_content")
    @patch("pecha_api.group_recitation_collection.cms_service.get_group_by_id")
    @patch("pecha_api.group_recitation_collection.cms_service.validate_and_extract_author_details")
    @patch("pecha_api.group_recitation_collection.cms_service.SessionLocal")
    def test_item_delete_drops_links_first(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_collection,
        mock_item,
        mock_drop_links,
        mock_soft_delete,
    ):
        from pecha_api.group_recitation_collection.cms_service import (
            cms_delete_item_service,
        )

        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_collection.return_value = MagicMock()
        mock_item.return_value = MagicMock()
        item_id = uuid4()

        cms_delete_item_service(
            token="token",
            group_id=uuid4(),
            collection_id=uuid4(),
            item_id=item_id,
        )

        mock_drop_links.assert_called_once()
        assert mock_drop_links.call_args.kwargs["item_id"] == item_id
        mock_soft_delete.assert_called_once()

    @patch("pecha_api.group_recitation_collection.cms_service.soft_delete_collection")
    @patch("pecha_api.group_recitation_collection.cms_service.delete_links_for_collection")
    @patch("pecha_api.group_recitation_collection.cms_service.get_collection_by_id")
    @patch("pecha_api.group_recitation_collection.cms_service.require_can_create_content")
    @patch("pecha_api.group_recitation_collection.cms_service.get_group_by_id")
    @patch("pecha_api.group_recitation_collection.cms_service.validate_and_extract_author_details")
    @patch("pecha_api.group_recitation_collection.cms_service.SessionLocal")
    def test_collection_delete_drops_links_first(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_collection,
        mock_drop_links,
        mock_soft_delete,
    ):
        from pecha_api.group_recitation_collection.cms_service import (
            cms_delete_collection_service,
        )

        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_collection.return_value = MagicMock()
        collection_id = uuid4()

        cms_delete_collection_service(
            token="token", group_id=uuid4(), collection_id=collection_id
        )

        mock_drop_links.assert_called_once()
        assert mock_drop_links.call_args.kwargs["collection_id"] == collection_id
        mock_soft_delete.assert_called_once()


class TestDeleteFailureHandling:
    """A failed S3 delete must not leave the DB claiming the asset is gone."""

    @patch(f"{SERVICE}.delete_file")
    @patch(f"{SERVICE}.soft_delete_asset")
    @patch(f"{SERVICE}.get_asset_usages")
    @patch(f"{SERVICE}.get_asset_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @pytest.mark.asyncio
    async def test_s3_failure_rolls_back_and_raises(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_get,
        mock_usages,
        mock_soft_delete,
        mock_delete_file,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_get.return_value = MockGroupAsset()
        mock_usages.return_value = []
        mock_delete_file.side_effect = Exception("S3 is down")

        with pytest.raises(HTTPException) as exc:
            await delete_group_asset_service(
                token="token", group_id=uuid4(), asset_id=uuid4()
            )

        assert exc.value.status_code == status.HTTP_502_BAD_GATEWAY
        mock_db.rollback.assert_called_once()
        mock_db.commit.assert_not_called()

    @patch(f"{SERVICE}.delete_file")
    @patch(f"{SERVICE}.soft_delete_asset")
    @patch(f"{SERVICE}.get_asset_usages")
    @patch(f"{SERVICE}.get_asset_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @pytest.mark.asyncio
    async def test_success_commits_once_after_s3_delete(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_get,
        mock_usages,
        mock_soft_delete,
        mock_delete_file,
    ):
        mock_db = MagicMock()
        mock_session.return_value.__enter__.return_value = mock_db
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_get.return_value = MockGroupAsset()
        mock_usages.return_value = []

        await delete_group_asset_service(
            token="token", group_id=uuid4(), asset_id=uuid4()
        )

        mock_delete_file.assert_called_once()
        mock_db.commit.assert_called_once()
        mock_db.rollback.assert_not_called()

    @patch(f"{SERVICE}.get_asset_by_id")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @pytest.mark.asyncio
    async def test_delete_locks_the_asset_row(
        self, mock_session, mock_author, mock_group, mock_perm, mock_get
    ):
        """The lock is what serialises deletion against a concurrent link."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_get.return_value = None

        with pytest.raises(HTTPException):
            await delete_group_asset_service(
                token="token", group_id=uuid4(), asset_id=uuid4()
            )

        assert mock_get.call_args.kwargs["for_update"] is True


class TestUploadCompensation:
    """A failed DB write must not leave the uploaded object behind."""

    @patch(f"{SERVICE}.delete_file")
    @patch(f"{SERVICE}.GroupAsset")
    @patch(f"{SERVICE}.create_asset")
    @patch(f"{SERVICE}.upload_file")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    def test_db_failure_discards_uploaded_object(
        self,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_upload,
        mock_create,
        mock_model,
        mock_delete_file,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_create.side_effect = Exception("db down")

        with pytest.raises(Exception, match="db down"):
            upload_group_asset_service(
                token="token",
                group_id=uuid4(),
                file=MockUploadFile(),
                asset_type=GroupAssetType.AUDIO,
            )

        # The orphan is cleaned up with the same key that was uploaded.
        mock_delete_file.assert_called_once()
        assert mock_delete_file.call_args[0][0] == mock_upload.call_args.kwargs["s3_key"]

    @patch(f"{SERVICE}.delete_file")
    @patch(f"{SERVICE}.GroupAsset")
    @patch(f"{SERVICE}.create_asset")
    @patch(f"{SERVICE}.upload_file")
    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    @patch(f"{SERVICE}.generate_asset_presigned_url")
    def test_successful_upload_discards_nothing(
        self,
        mock_presign,
        mock_session,
        mock_author,
        mock_group,
        mock_perm,
        mock_upload,
        mock_create,
        mock_model,
        mock_delete_file,
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_create.return_value = MockGroupAsset()
        mock_presign.return_value = "https://presigned"

        upload_group_asset_service(
            token="token",
            group_id=uuid4(),
            file=MockUploadFile(),
            asset_type=GroupAssetType.AUDIO,
        )

        mock_delete_file.assert_not_called()
