from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from pecha_api.plans.groups.groups_enums import AuthorGroupMemberRole, AuthorGroupType
from pecha_api.plans.groups.groups_service import (
    _assert_can_manage_group_settings,
    _is_platform_manager_of,
)

SERVICE = "pecha_api.plans.groups.groups_service"


def _author(role):
    return SimpleNamespace(id=uuid4(), platform_role=role, is_active=True)


def _group(group_type):
    return SimpleNamespace(id=uuid4(), group_type=group_type)


def test_content_admin_manages_any_page():
    assert _is_platform_manager_of(_author("CONTENT_ADMIN"), _group(AuthorGroupType.PAGE))


def test_content_admin_does_not_manage_communities():
    assert not _is_platform_manager_of(_author("CONTENT_ADMIN"), _group(AuthorGroupType.COMMUNITY))


@pytest.mark.parametrize("role", ["CREATOR", "REVIEWER"])
def test_other_roles_do_not_manage_pages(role):
    assert not _is_platform_manager_of(_author(role), _group(AuthorGroupType.PAGE))


def test_super_admin_manages_everything():
    for group_type in AuthorGroupType:
        assert _is_platform_manager_of(_author("SUPER_ADMIN"), _group(group_type))


def test_content_admin_needs_no_membership_on_a_page():
    with patch(f"{SERVICE}.get_group_member") as get_member:
        _assert_can_manage_group_settings(
            MagicMock(), group=_group(AuthorGroupType.PAGE), author=_author("CONTENT_ADMIN")
        )
    get_member.assert_not_called()


def test_content_admin_still_needs_membership_on_a_community():
    with patch(f"{SERVICE}.get_group_member", return_value=None):
        with pytest.raises(HTTPException) as exc:
            _assert_can_manage_group_settings(
                MagicMock(), group=_group(AuthorGroupType.COMMUNITY), author=_author("CONTENT_ADMIN")
            )
    assert exc.value.status_code == 403


def test_content_admin_member_of_a_community_follows_member_roles():
    member = SimpleNamespace(role=AuthorGroupMemberRole.OWNER)
    with patch(f"{SERVICE}.get_group_member", return_value=member):
        _assert_can_manage_group_settings(
            MagicMock(), group=_group(AuthorGroupType.COMMUNITY), author=_author("CONTENT_ADMIN")
        )
