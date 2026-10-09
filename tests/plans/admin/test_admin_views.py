import uuid
from unittest.mock import patch

from pecha_api.plans.admin.admin_response_models import (
    AdminAuthorActivateResponse,
    AdminAuthorDetailDTO,
    AdminAuthorListResponse,
)
from pecha_api.plans.admin.admin_views import (
    get_cms_admin_author_detail,
    get_cms_admin_authors,
    post_cms_admin_author_activate,
)
from pecha_api.plans.platform_enums import PlatformRole


def test_get_cms_admin_authors_delegates_to_service():
    expected = AdminAuthorListResponse(authors=[], skip=0, limit=20, total=0)

    with patch(
        "pecha_api.plans.admin.admin_views.list_admin_authors",
        return_value=expected,
    ) as mock_service:
        resp = get_cms_admin_authors(
            skip=0,
            limit=20,
            is_verified=None,
            is_active=None,
            platform_role=None,
            search=None,
            token="token123",
        )

    assert resp == expected
    mock_service.assert_called_once_with(
        token="token123",
        skip=0,
        limit=20,
        is_verified=None,
        is_active=None,
        platform_role=None,
        search=None,
        account_status_filter=None,
    )


def test_get_cms_admin_author_detail_delegates_to_service():
    author_id = uuid.uuid4()
    expected = AdminAuthorDetailDTO(
        id=author_id,
        firstname="A",
        lastname="B",
        email="a@example.com",
        is_verified=True,
        is_active=True,
        platform_role=PlatformRole.CREATOR,
    )

    with patch(
        "pecha_api.plans.admin.admin_views.get_admin_author_detail",
        return_value=expected,
    ) as mock_service:
        resp = get_cms_admin_author_detail(author_id=author_id, token="token123")

    assert resp == expected
    mock_service.assert_called_once_with(token="token123", author_id=author_id)


def test_post_cms_admin_author_activate_delegates_to_service():
    author_id = uuid.uuid4()
    expected = AdminAuthorActivateResponse(id=author_id, is_active=True)

    with patch(
        "pecha_api.plans.admin.admin_views.activate_author",
        return_value=expected,
    ) as mock_service:
        resp = post_cms_admin_author_activate(author_id=author_id, token="token123")

    assert resp == expected
    mock_service.assert_called_once_with(token="token123", author_id=author_id)
