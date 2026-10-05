import uuid
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from starlette import status

from pecha_api.plans.admin.admin_response_models import AdminAuthorPlatformRoleUpdate
from pecha_api.plans.admin.admin_service import (
    activate_author,
    get_admin_author_detail,
    list_admin_authors,
    suspend_author,
    update_author_platform_role,
)
from pecha_api.plans.platform_enums import PlatformRole


def _session_local_context(mock_session_local):
    mock_db = MagicMock()
    mock_session_local.return_value.__enter__.return_value = mock_db
    mock_session_local.return_value.__exit__.return_value = False
    return mock_db


def _make_author(
    *,
    author_id=None,
    email="admin@example.com",
    phone_number=None,
    platform_role=PlatformRole.SUPER_ADMIN,
    is_active=True,
    is_verified=True,
):
    author = MagicMock()
    author.id = author_id or uuid.uuid4()
    author.email = email
    author.phone_number = phone_number
    author.first_name = "Admin"
    author.last_name = "User"
    author.platform_role = platform_role.value
    author.is_active = is_active
    author.is_verified = is_verified
    author.bio = None
    author.image_url = None
    author.created_at = datetime.now(timezone.utc)
    author.suspended_at = None
    return author


def test_list_admin_authors_success():
    row = _make_author()
    caller = _make_author(platform_role=PlatformRole.REVIEWER)

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ), patch("pecha_api.plans.admin.admin_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.admin.admin_service.list_authors_admin",
        return_value=([row], 1),
    ):
        _session_local_context(mock_session_local)
        resp = list_admin_authors(
            token="token",
            skip=0,
            limit=20,
            is_verified=True,
            is_active=True,
            platform_role=PlatformRole.CREATOR,
            search="admin",
        )

    assert resp.total == 1
    assert resp.authors[0].email == row.email
    assert resp.authors[0].platform_role == PlatformRole.SUPER_ADMIN


def test_list_admin_authors_includes_phone_only_authors():
    row = _make_author(email=None, phone_number="+919812345678", is_active=False)
    caller = _make_author(platform_role=PlatformRole.SUPER_ADMIN)

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ), patch("pecha_api.plans.admin.admin_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.admin.admin_service.list_authors_admin",
        return_value=([row], 1),
    ):
        _session_local_context(mock_session_local)
        resp = list_admin_authors(
            token="token",
            skip=0,
            limit=20,
            is_verified=True,
            is_active=False,
        )

    assert resp.authors[0].email is None
    assert resp.authors[0].phone_number == "+919812345678"


def test_get_admin_author_detail_phone_only_author():
    target = _make_author(email=None, phone_number="+919812345678")
    caller = _make_author(platform_role=PlatformRole.SUPER_ADMIN)

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ), patch("pecha_api.plans.admin.admin_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.admin.admin_service.get_author_by_id",
        return_value=target,
    ):
        _session_local_context(mock_session_local)
        dto = get_admin_author_detail(token="token", author_id=target.id)

    assert dto.email is None
    assert dto.phone_number == "+919812345678"


def test_list_admin_authors_forbidden_for_creator():
    caller = _make_author(platform_role=PlatformRole.CREATOR)

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ):
        with pytest.raises(HTTPException) as exc_info:
            list_admin_authors(token="token", skip=0, limit=20)

    assert exc_info.value.status_code == status.HTTP_403_FORBIDDEN


def test_get_admin_author_detail_success():
    target = _make_author(email="target@example.com")
    caller = _make_author(platform_role=PlatformRole.SUPER_ADMIN)

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ), patch("pecha_api.plans.admin.admin_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.admin.admin_service.get_author_by_id",
        return_value=target,
    ):
        _session_local_context(mock_session_local)
        dto = get_admin_author_detail(token="token", author_id=target.id)

    assert dto.email == "target@example.com"
    assert dto.platform_role == PlatformRole.SUPER_ADMIN


def test_activate_author_success():
    target = _make_author(is_active=False)
    caller = _make_author(platform_role=PlatformRole.SUPER_ADMIN)
    saved = _make_author(is_active=True)
    saved.id = target.id

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ), patch("pecha_api.plans.admin.admin_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.admin.admin_service.get_author_by_id",
        return_value=target,
    ), patch(
        "pecha_api.plans.admin.admin_service.save_author",
        return_value=saved,
    ), patch(
        "pecha_api.plans.admin.admin_service.on_author_activated_by_admin",
    ) as mock_approved:
        _session_local_context(mock_session_local)
        resp = activate_author(token="token", author_id=target.id)

    assert resp.is_active is True
    assert target.is_active is True
    mock_approved.assert_called_once()
    assert mock_approved.call_args.kwargs == {"was_suspended": False}


def test_activate_author_clears_suspension_and_reports_it():
    target = _make_author(is_active=False)
    target.suspended_at = datetime.now(timezone.utc)
    caller = _make_author(platform_role=PlatformRole.SUPER_ADMIN)

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ), patch("pecha_api.plans.admin.admin_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.admin.admin_service.get_author_by_id",
        return_value=target,
    ), patch(
        "pecha_api.plans.admin.admin_service.save_author",
        side_effect=lambda db, author: author,
    ), patch(
        "pecha_api.plans.admin.admin_service.on_author_activated_by_admin",
    ) as mock_approved:
        _session_local_context(mock_session_local)
        activate_author(token="token", author_id=target.id)

    assert target.suspended_at is None
    assert mock_approved.call_args.kwargs == {"was_suspended": True}


def test_activate_already_active_author_sends_nothing():
    target = _make_author(is_active=True)
    caller = _make_author(platform_role=PlatformRole.SUPER_ADMIN)

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ), patch("pecha_api.plans.admin.admin_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.admin.admin_service.get_author_by_id",
        return_value=target,
    ), patch(
        "pecha_api.plans.admin.admin_service.save_author",
        side_effect=lambda db, author: author,
    ), patch(
        "pecha_api.plans.admin.admin_service.on_author_activated_by_admin",
    ) as mock_approved:
        _session_local_context(mock_session_local)
        activate_author(token="token", author_id=target.id)

    mock_approved.assert_not_called()


def test_suspend_author_success():
    target = _make_author(platform_role=PlatformRole.CREATOR, is_active=True)
    caller = _make_author(platform_role=PlatformRole.SUPER_ADMIN)
    saved = _make_author(platform_role=PlatformRole.CREATOR, is_active=False)
    saved.id = target.id

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ), patch("pecha_api.plans.admin.admin_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.admin.admin_service.get_author_by_id",
        return_value=target,
    ), patch(
        "pecha_api.plans.admin.admin_service.count_super_admins",
        return_value=2,
    ), patch(
        "pecha_api.plans.admin.admin_service.save_author",
        return_value=saved,
    ):
        _session_local_context(mock_session_local)
        resp = suspend_author(token="token", author_id=target.id)

    assert resp.is_active is False
    assert target.suspended_at is not None


def test_get_admin_author_detail_with_image():
    target = _make_author(email="target@example.com")
    target.image_url = "authors/photo.jpg"
    caller = _make_author(platform_role=PlatformRole.SUPER_ADMIN)

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ), patch("pecha_api.plans.admin.admin_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.admin.admin_service.get_author_by_id",
        return_value=target,
    ), patch(
        "pecha_api.plans.admin.admin_service.generate_presigned_access_url",
        return_value="https://signed.example/photo.jpg",
    ):
        _session_local_context(mock_session_local)
        dto = get_admin_author_detail(token="token", author_id=target.id)

    assert dto.image_url == "https://signed.example/photo.jpg"


def test_suspend_author_blocks_last_super_admin():
    target = _make_author(platform_role=PlatformRole.SUPER_ADMIN)
    caller = _make_author(platform_role=PlatformRole.SUPER_ADMIN)

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ), patch("pecha_api.plans.admin.admin_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.admin.admin_service.get_author_by_id",
        return_value=target,
    ), patch(
        "pecha_api.plans.admin.admin_service.count_super_admins",
        return_value=1,
    ):
        _session_local_context(mock_session_local)
        with pytest.raises(HTTPException) as exc_info:
            suspend_author(token="token", author_id=target.id)

    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST


def test_update_author_platform_role_success():
    target = _make_author(platform_role=PlatformRole.CREATOR)
    caller = _make_author(platform_role=PlatformRole.SUPER_ADMIN)
    saved = _make_author(platform_role=PlatformRole.REVIEWER)
    saved.id = target.id

    with patch(
        "pecha_api.plans.admin.admin_service.validate_and_extract_author_details",
        return_value=caller,
    ), patch("pecha_api.plans.admin.admin_service.SessionLocal") as mock_session_local, patch(
        "pecha_api.plans.admin.admin_service.get_author_by_id",
        return_value=target,
    ), patch(
        "pecha_api.plans.admin.admin_service.save_author",
        return_value=saved,
    ):
        _session_local_context(mock_session_local)
        dto = update_author_platform_role(
            token="token",
            author_id=target.id,
            body=AdminAuthorPlatformRoleUpdate(platform_role=PlatformRole.REVIEWER),
        )

    assert dto.platform_role == PlatformRole.REVIEWER
