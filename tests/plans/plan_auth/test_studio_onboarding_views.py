"""Routing for the onboarding endpoints: the public pages a /join link opens,
and the group-manager endpoints for bulk invites and join links."""
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient

from pecha_api.app import api
from pecha_api.plans.auth.plan_auth_enums import AuthorStatus
from pecha_api.plans.auth.plan_auth_models import AppLoginResponse, AuthorInfo, AuthorLoginResponse, TokenResponse
from pecha_api.plans.groups.groups_enums import AuthorGroupInviteStatus, AuthorGroupMemberRole
from pecha_api.plans.groups.groups_response_models import (
    BulkGroupInviteResponse,
    GroupInvitePreviewDTO,
    GroupJoinLinkPreviewDTO,
    GroupJoinLinkRedeemResponse,
)

client = TestClient(api)
AUTH = {"Authorization": "Bearer t"}


def test_invite_preview_is_public():
    preview = GroupInvitePreviewDTO(
        invite_id=uuid4(),
        group_id=uuid4(),
        group_name="Sangha",
        role=AuthorGroupMemberRole.AUTHOR,
        target_email="tenzin@example.org",
        inviter_name="Karma",
        status=AuthorGroupInviteStatus.PENDING,
        expires_at=datetime.now(timezone.utc) + timedelta(days=7),
        account_exists=False,
    )
    with patch("pecha_api.plans.auth.plan_auth_views.get_invite_preview", return_value=preview) as svc:
        response = client.get("cms/auth/invites/preview", params={"token": "tok"})
    assert response.status_code == 200
    assert response.json()["group_name"] == "Sangha"
    svc.assert_called_once_with(invite_token="tok")


def test_invite_register_returns_tokens():
    login = AuthorLoginResponse(
        user=AuthorInfo(name="Tenzin Dolma"),
        auth=TokenResponse(access_token="a", refresh_token="r", token_type="Bearer"),
        joined_group_ids=[uuid4()],
    )
    with patch("pecha_api.plans.auth.plan_auth_views.register_author_from_invite", return_value=login):
        response = client.post(
            "cms/auth/invites/register",
            json={"invite_token": "tok", "first_name": "Tenzin", "last_name": "Dolma", "password": "secret123"},
        )
    assert response.status_code == 201
    assert response.json()["auth"]["access_token"] == "a"
    assert len(response.json()["joined_group_ids"]) == 1


def test_login_forwards_invite_and_join_link_tokens():
    login = AuthorLoginResponse(
        user=AuthorInfo(name="Tenzin Dolma"),
        auth=TokenResponse(access_token="a", refresh_token="r", token_type="Bearer"),
    )
    with patch("pecha_api.plans.auth.plan_auth_views.authenticate_and_generate_tokens", return_value=login) as svc:
        response = client.post(
            "cms/auth/login",
            json={"email": "a@example.org", "password": "pw", "invite_token": "inv", "join_link_token": "lnk"},
        )
    assert response.status_code == 200
    svc.assert_called_once_with(email="a@example.org", password="pw", invite_token="inv", join_link_token="lnk")


def test_join_link_preview_is_public():
    preview = GroupJoinLinkPreviewDTO(
        group_id=uuid4(),
        group_name="Sangha",
        role=AuthorGroupMemberRole.AUTHOR,
        expires_at=datetime.now(timezone.utc) + timedelta(days=14),
        is_usable=True,
    )
    with patch("pecha_api.plans.auth.plan_auth_views.get_join_link_preview", return_value=preview):
        response = client.get("cms/auth/join-links/preview", params={"token": "tok"})
    assert response.status_code == 200
    assert response.json()["is_usable"] is True


def test_app_login_route():
    reply = AppLoginResponse(
        author_id=uuid4(),
        email="a@example.org",
        status=AuthorStatus.ACTIVE,
        account_status=AuthorStatus.ACTIVE,
        message="Authentication successful",
        user=AuthorInfo(name="A B"),
    )
    with patch("pecha_api.plans.auth.plan_auth_views.login_with_app_account", return_value=reply):
        response = client.post("cms/auth/app/login", json={"email": "a@example.org", "password": "pw"})
    assert response.status_code == 200
    assert response.json()["account_status"] == "ACTIVE"


def test_bulk_invite_route():
    group_id = uuid4()
    with patch(
        "pecha_api.plans.groups.groups_views.create_group_member_invites_bulk",
        return_value=BulkGroupInviteResponse(invites=[], skipped=[]),
    ) as svc:
        response = client.post(
            f"cms/author/groups/{group_id}/members/invites/bulk",
            json={"target_emails": ["a@example.org"], "role": "AUTHOR"},
            headers=AUTH,
        )
    assert response.status_code == 201
    assert svc.call_args.kwargs["group_id"] == group_id


def test_redeem_route_is_not_shadowed_by_group_routes():
    redeemed = GroupJoinLinkRedeemResponse(
        group_id=uuid4(), group_name="Sangha", role=AuthorGroupMemberRole.AUTHOR, already_member=False
    )
    with patch(
        "pecha_api.plans.groups.groups_views.redeem_join_link_for_signed_in_author",
        return_value=redeemed,
    ) as svc:
        response = client.post("cms/author/groups/join-links/redeem", json={"token": "lnk"}, headers=AUTH)
    assert response.status_code == 200
    assert svc.call_args.kwargs["request"].token == "lnk"


def test_join_link_revoke_route():
    group_id, link_id = uuid4(), uuid4()
    with patch("pecha_api.plans.groups.groups_views.revoke_group_join_link") as svc:
        response = client.post(f"cms/author/groups/{group_id}/join-links/{link_id}/revoke", headers=AUTH)
    assert response.status_code == 204
    svc.assert_called_once_with(token="t", group_id=group_id, link_id=link_id)
