from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.plans.platform_enums import PlatformRole
from pecha_api.plans.shared import permissions
from pecha_api.plans.shared.permissions import (
    build_author_access_context,
    get_platform_role,
    is_content_admin,
    is_platform_read_only,
    is_reviewer,
    is_super_admin,
    require_cms_write_access,
    require_content_manager,
    require_super_admin,
    require_super_admin_or_reviewer,
)


def _author(role: str) -> SimpleNamespace:
    return SimpleNamespace(id=uuid4(), platform_role=role, is_active=True, is_verified=True)


CONTENT_ADMIN = "CONTENT_ADMIN"


def test_content_admin_is_a_fourth_platform_role():
    assert {role.value for role in PlatformRole} == {
        "SUPER_ADMIN",
        "REVIEWER",
        "CREATOR",
        "CONTENT_ADMIN",
    }
    assert get_platform_role(_author(CONTENT_ADMIN)) is PlatformRole.CONTENT_ADMIN
    assert get_platform_role(_author(PlatformRole.CONTENT_ADMIN)) is PlatformRole.CONTENT_ADMIN


def test_content_admin_is_neither_super_admin_nor_reviewer():
    author = _author(CONTENT_ADMIN)
    assert is_content_admin(author)
    # Seeing every plan and space hangs on these two; a content admin has neither.
    assert not is_super_admin(author)
    assert not is_reviewer(author)
    assert not is_platform_read_only(author)


@pytest.mark.parametrize("role", ["CREATOR", "REVIEWER", "SUPER_ADMIN"])
def test_other_roles_are_not_content_admin(role):
    assert not is_content_admin(_author(role))


def test_content_manager_gate_admits_super_admin_and_content_admin_only():
    require_content_manager(_author("SUPER_ADMIN"))
    require_content_manager(_author(CONTENT_ADMIN))
    for role in ("CREATOR", "REVIEWER"):
        with pytest.raises(HTTPException) as caught:
            require_content_manager(_author(role))
        assert caught.value.status_code == 403


def test_content_admin_keeps_out_of_super_admin_administration():
    author = _author(CONTENT_ADMIN)
    with pytest.raises(HTTPException) as caught:
        require_super_admin(author)
    assert caught.value.status_code == 403
    with pytest.raises(HTTPException):
        require_super_admin_or_reviewer(author)


def test_content_admin_can_write_like_a_creator():
    require_cms_write_access(_author(CONTENT_ADMIN))


@pytest.mark.parametrize(
    "role, has_group, expected",
    [
        (CONTENT_ADMIN, True, True),
        (CONTENT_ADMIN, False, False),
        ("CREATOR", True, True),
        ("REVIEWER", True, False),
    ],
)
def test_can_create_content_for_content_admin_matches_a_creator(role, has_group, expected):
    with patch.object(permissions, "author_has_any_group", return_value=has_group):
        context = build_author_access_context(MagicMock(), _author(role))
    assert context["can_create_content"] is expected


def test_access_context_reports_the_role():
    with patch.object(permissions, "author_has_any_group", return_value=False):
        context = build_author_access_context(MagicMock(), _author(CONTENT_ADMIN))
    assert context["platform_role"] is PlatformRole.CONTENT_ADMIN


def test_ambient_sound_catalogue_is_open_to_content_admins_but_not_creators():
    from pecha_api.ambient_sounds import ambient_sound_service

    for role, allowed in (("SUPER_ADMIN", True), (CONTENT_ADMIN, True), ("CREATOR", False), ("REVIEWER", False)):
        with patch.object(
            ambient_sound_service, "validate_cms_author_details", return_value=_author(role)
        ):
            if allowed:
                ambient_sound_service._validate_admin("token")
            else:
                with pytest.raises(HTTPException) as caught:
                    ambient_sound_service._validate_admin("token")
                assert caught.value.status_code == 403


def test_super_admin_can_assign_the_role():
    from pecha_api.plans.admin.admin_response_models import AdminAuthorPlatformRoleUpdate

    body = AdminAuthorPlatformRoleUpdate(platform_role="CONTENT_ADMIN")
    assert body.platform_role is PlatformRole.CONTENT_ADMIN
