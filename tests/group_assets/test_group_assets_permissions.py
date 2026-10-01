"""Permission tests for group assets.

The routes delegate to the shared helpers, so these assert the contract those
helpers enforce: a VIEWER may browse the library but not change it, and a
platform reviewer may do neither.
"""
import pytest
from unittest.mock import patch, MagicMock
from uuid import uuid4

from fastapi import HTTPException
from starlette import status

from pecha_api.group_assets.enums import GroupAssetType
from pecha_api.group_assets.service import (
    list_group_assets_service,
    update_group_asset_service,
    upload_group_asset_service,
)
from pecha_api.group_assets.response_models import UpdateGroupAssetRequest
from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole
from pecha_api.plans.shared.permissions import (
    require_can_create_content,
    require_can_read_group_content,
)

SERVICE = "pecha_api.group_assets.service"
PERMISSIONS = "pecha_api.plans.shared.permissions"


class MockAuthor:
    def __init__(self, email="viewer@example.com"):
        self.id = uuid4()
        self.email = email


class MockMember:
    def __init__(self, role):
        self.role = role


class MockUploadFile:
    def __init__(self):
        self.filename = "chant.mp3"
        self.size = 1024
        self.content_type = "audio/mpeg"
        self.file = MagicMock()


class TestRoleContract:
    """The helper the asset routes call decides these, so pin the behaviour."""

    @patch(f"{PERMISSIONS}.is_reviewer", return_value=False)
    @patch(f"{PERMISSIONS}.is_super_admin", return_value=False)
    @patch(f"{PERMISSIONS}.get_group_member")
    def test_viewer_can_read_group_content(
        self, mock_member, mock_admin, mock_reviewer
    ):
        mock_member.return_value = MockMember(AuthorGroupMemberRole.VIEWER)

        require_can_read_group_content(
            db=MagicMock(), group_id=uuid4(), author=MockAuthor()
        )

    @patch(f"{PERMISSIONS}.is_platform_read_only", return_value=False)
    @patch(f"{PERMISSIONS}.is_super_admin", return_value=False)
    @patch(f"{PERMISSIONS}.get_group_member")
    def test_viewer_cannot_create_content(
        self, mock_member, mock_admin, mock_read_only
    ):
        mock_member.return_value = MockMember(AuthorGroupMemberRole.VIEWER)

        with pytest.raises(HTTPException) as exc:
            require_can_create_content(
                db=MagicMock(), group_id=uuid4(), author=MockAuthor()
            )
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    @patch(f"{PERMISSIONS}.is_platform_read_only", return_value=True)
    def test_platform_reviewer_cannot_create_content(self, mock_read_only):
        with pytest.raises(HTTPException) as exc:
            require_can_create_content(
                db=MagicMock(), group_id=uuid4(), author=MockAuthor()
            )
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    @pytest.mark.parametrize(
        "role",
        [
            AuthorGroupMemberRole.OWNER,
            AuthorGroupMemberRole.ADMIN,
            AuthorGroupMemberRole.AUTHOR,
        ],
    )
    @patch(f"{PERMISSIONS}.is_platform_read_only", return_value=False)
    @patch(f"{PERMISSIONS}.is_super_admin", return_value=False)
    @patch(f"{PERMISSIONS}.get_group_member")
    def test_content_roles_can_create(
        self, mock_member, mock_admin, mock_read_only, role
    ):
        mock_member.return_value = MockMember(role)

        require_can_create_content(
            db=MagicMock(), group_id=uuid4(), author=MockAuthor()
        )


class TestAssetRoutesUseTheRightHelper:
    """A 403 from the helper must propagate rather than being swallowed."""

    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    def test_upload_propagates_forbidden(
        self, mock_session, mock_author, mock_group, mock_perm
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_perm.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"
        )

        with pytest.raises(HTTPException) as exc:
            upload_group_asset_service(
                token="token",
                group_id=uuid4(),
                file=MockUploadFile(),
                asset_type=GroupAssetType.AUDIO,
            )
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    @patch(f"{SERVICE}.require_can_create_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    def test_rename_propagates_forbidden(
        self, mock_session, mock_author, mock_group, mock_perm
    ):
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_perm.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"
        )

        with pytest.raises(HTTPException) as exc:
            update_group_asset_service(
                token="token",
                group_id=uuid4(),
                asset_id=uuid4(),
                request=UpdateGroupAssetRequest(title="x"),
            )
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN

    @patch(f"{SERVICE}.get_group_assets")
    @patch(f"{SERVICE}.require_can_read_group_content")
    @patch(f"{SERVICE}.get_group_by_id")
    @patch(f"{SERVICE}.validate_and_extract_author_details")
    @patch(f"{SERVICE}.SessionLocal")
    def test_list_uses_the_read_helper_not_the_write_one(
        self, mock_session, mock_author, mock_group, mock_read_perm, mock_assets
    ):
        """Listing must gate on read access, so a VIEWER can browse."""
        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_assets.return_value = ([], 0)

        list_group_assets_service(token="token", group_id=uuid4())

        mock_read_perm.assert_called_once()


class TestItemAudioPermissions:
    @patch("pecha_api.group_assets.item_assets_service.require_can_create_content")
    @patch("pecha_api.group_assets.item_assets_service.get_group_by_id")
    @patch(
        "pecha_api.group_assets.item_assets_service.validate_and_extract_author_details"
    )
    @patch("pecha_api.group_assets.item_assets_service.SessionLocal")
    @pytest.mark.asyncio
    async def test_linking_propagates_forbidden(
        self, mock_session, mock_author, mock_group, mock_perm
    ):
        from pecha_api.group_assets.item_assets_service import set_item_audio_service

        mock_session.return_value.__enter__.return_value = MagicMock()
        mock_author.return_value = MockAuthor()
        mock_group.return_value = MagicMock()
        mock_perm.side_effect = HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden"
        )

        with pytest.raises(HTTPException) as exc:
            await set_item_audio_service(
                token="token",
                group_id=uuid4(),
                collection_id=uuid4(),
                item_id=uuid4(),
                asset_ids=[],
            )
        assert exc.value.status_code == status.HTTP_403_FORBIDDEN
